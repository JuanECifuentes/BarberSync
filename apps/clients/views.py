"""
Client CRM views – ag-Grid, KPIs, CRUD, Ficha Clínica PDF, Profile.
Scoped to the user's organization.
"""

import io
import json
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import (
    Count, DecimalField, F, Q, Sum, Value, Subquery, OuterRef,
)
from django.db.models.functions import Coalesce
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import Barbershop
from apps.core.mixins import OrganizationViewMixin, RoleRequiredMixin
from apps.scheduling.models import Intervencion, IntervencionServicio, IntervencionProducto

from .models import Client, FichaClinica


# ─────────────────────────────────────────────
# Helper: money formatting
# ─────────────────────────────────────────────
def _format_money(value):
    """Format number with dot as thousands separator (Colombian style)."""
    try:
        rounded = int(Decimal(str(value)).quantize(Decimal("1")))
        return f"{rounded:,}".replace(",", ".")
    except Exception:
        return str(value)


# ─────────────────────────────────────────────
# Main list page (renders ag-Grid template)
# ─────────────────────────────────────────────
class ClientListView(LoginRequiredMixin, TemplateView):
    template_name = "clients/client_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.organization

        # KPIs — only count intervenciones with estado="realizada"
        realizada_filter = Q(estado=Intervencion.Estado.REALIZADA)

        active_clients = Client.objects.filter(organization=org, is_active=True)
        ctx["total_clientes"] = active_clients.count()

        ctx["total_visitas"] = Intervencion.objects.filter(
            realizada_filter,
            client__organization=org,
            client__is_active=True,
        ).count()

        svc_total = IntervencionServicio.objects.filter(
            intervencion__client__organization=org,
            intervencion__client__is_active=True,
            intervencion__estado=Intervencion.Estado.REALIZADA,
        ).aggregate(total=Coalesce(Sum("precio_cobrado"), Value(Decimal("0"))))["total"]

        prod_total = IntervencionProducto.objects.filter(
            intervencion__client__organization=org,
            intervencion__client__is_active=True,
            intervencion__estado=Intervencion.Estado.REALIZADA,
        ).aggregate(
            total=Coalesce(
                Sum(F("cantidad") * F("precio_unitario")),
                Value(Decimal("0")),
            )
        )["total"]

        ctx["total_ingresos"] = _format_money(svc_total + prod_total)

        # Sucursales for filters
        ctx["sucursales"] = Barbershop.objects.filter(organization=org, is_active=True)

        return ctx


# ─────────────────────────────────────────────
# ag-Grid API: filtrado, ordenamiento, paginación
# ─────────────────────────────────────────────
class ClientGridAPI(LoginRequiredMixin, View):
    """
    API endpoint for ag-Grid infinite row model.
    Supports external filters via GET params (NOT query params in URL).
    """

    def get(self, request):
        org = getattr(request, "organization", None)
        if org is None:
            return JsonResponse({"error": "Sin organización"}, status=403)

        qs = Client.objects.filter(organization=org, is_active=True)

        # Only count intervenciones with estado="realizada"
        realizada_q = Q(intervenciones__estado=Intervencion.Estado.REALIZADA)

        # Annotate visit count (only realizada)
        qs = qs.annotate(
            visitas=Count("intervenciones", filter=realizada_q, distinct=True),
        )

        # Use Subquery for gastos to avoid cartesian product when JOINing
        # services and products tables simultaneously
        svc_subquery = Subquery(
            IntervencionServicio.objects.filter(
                intervencion__client=OuterRef("pk"),
                intervencion__estado=Intervencion.Estado.REALIZADA,
            ).values("intervencion__client").annotate(
                total=Sum("precio_cobrado"),
            ).values("total")[:1],
            output_field=DecimalField(),
        )
        prod_subquery = Subquery(
            IntervencionProducto.objects.filter(
                intervencion__client=OuterRef("pk"),
                intervencion__estado=Intervencion.Estado.REALIZADA,
            ).values("intervencion__client").annotate(
                total=Sum(F("cantidad") * F("precio_unitario")),
            ).values("total")[:1],
            output_field=DecimalField(),
        )
        qs = qs.annotate(
            _total_servicios=Coalesce(svc_subquery, Value(Decimal("0"))),
            _total_productos=Coalesce(prod_subquery, Value(Decimal("0"))),
            gastos=F("_total_servicios") + F("_total_productos"),
        )

        # ── Filtros externos ──

        # Nombre
        filter_nombre = request.GET.get("filter_nombre", "").strip()
        if filter_nombre:
            qs = qs.filter(name__icontains=filter_nombre)

        # Email
        filter_email = request.GET.get("filter_email", "").strip()
        if filter_email:
            qs = qs.filter(email__icontains=filter_email)

        # Teléfono
        filter_telefono = request.GET.get("filter_telefono", "").strip()
        if filter_telefono:
            qs = qs.filter(phone__icontains=filter_telefono)

        # Rango de visitas
        filter_visitas_min = request.GET.get("filter_visitas_min", "").strip()
        if filter_visitas_min:
            try:
                qs = qs.filter(visitas__gte=int(filter_visitas_min))
            except ValueError:
                pass

        filter_visitas_max = request.GET.get("filter_visitas_max", "").strip()
        if filter_visitas_max:
            try:
                qs = qs.filter(visitas__lte=int(filter_visitas_max))
            except ValueError:
                pass

        # Rango de gastos
        filter_gastos_min = request.GET.get("filter_gastos_min", "").strip()
        if filter_gastos_min:
            try:
                qs = qs.filter(gastos__gte=Decimal(filter_gastos_min))
            except (InvalidOperation, ValueError):
                pass

        filter_gastos_max = request.GET.get("filter_gastos_max", "").strip()
        if filter_gastos_max:
            try:
                qs = qs.filter(gastos__lte=Decimal(filter_gastos_max))
            except (InvalidOperation, ValueError):
                pass

        # Rango de fechas de asistencia (intervenciones)
        filter_fecha_desde = request.GET.get("filter_fecha_desde", "").strip()
        filter_fecha_hasta = request.GET.get("filter_fecha_hasta", "").strip()
        if filter_fecha_desde or filter_fecha_hasta:
            interv_filter = Q()
            if filter_fecha_desde:
                interv_filter &= Q(intervenciones__fecha__date__gte=filter_fecha_desde)
            if filter_fecha_hasta:
                interv_filter &= Q(intervenciones__fecha__date__lte=filter_fecha_hasta)
            qs = qs.filter(interv_filter).distinct()

        # Sucursales (comma-separated IDs)
        filter_sucursales = request.GET.get("filter_sucursales", "").strip()
        if filter_sucursales:
            ids = [int(x) for x in filter_sucursales.split(",") if x.strip().isdigit()]
            if ids:
                qs = qs.filter(intervenciones__barbershop_id__in=ids).distinct()

        # ── Ordenamiento ──
        sort_field = request.GET.get("sort", "name")
        sort_order = request.GET.get("order", "asc")

        sort_map = {
            "nombre": "name",
            "email": "email",
            "telefono": "phone",
            "visitas": "visitas",
            "gastos": "gastos",
        }
        db_field = sort_map.get(sort_field, "name")
        if sort_order == "desc":
            db_field = f"-{db_field}"
        qs = qs.order_by(db_field)

        # ── Paginación ──
        total_count = qs.count()

        try:
            start_row = int(request.GET.get("startRow", 0))
            end_row = int(request.GET.get("endRow", 30))
        except (ValueError, TypeError):
            start_row, end_row = 0, 30

        page = qs[start_row:end_row]

        # ── Serializar ──
        # Pre-fetch ficha clinica existence
        client_ids = [c.pk for c in page]
        fichas_exist = set(
            FichaClinica.objects.filter(client_id__in=client_ids)
            .values_list("client_id", flat=True)
            .distinct()
        )

        rows = []
        for c in page:
            rows.append({
                "id": c.pk,
                "nombre": c.name,
                "email": c.email,
                "telefono": c.phone,
                "visitas": c.visitas,
                "gastos": str(c.gastos),
                "gastos_fmt": f"${_format_money(c.gastos)}",
                "tiene_ficha": c.pk in fichas_exist,
                "notas": c.notes,
                "source": c.source,
            })

        last_row = total_count if end_row >= total_count else -1

        # ── KPIs reactivos (basados en el queryset filtrado) ──
        kpi_agg = qs.aggregate(
            kpi_total_clientes=Count("pk", distinct=True),
            kpi_total_visitas=Sum("visitas"),
            kpi_total_gastos=Sum("gastos"),
        )
        kpi_clientes = kpi_agg["kpi_total_clientes"] or 0
        kpi_visitas = kpi_agg["kpi_total_visitas"] or 0
        kpi_gastos = kpi_agg["kpi_total_gastos"] or Decimal("0")

        return JsonResponse({
            "rows": rows,
            "lastRow": last_row,
            "kpis": {
                "total_clientes": kpi_clientes,
                "total_visitas": kpi_visitas,
                "total_ingresos": f"${_format_money(kpi_gastos)}",
            },
        })


# ─────────────────────────────────────────────
# CRUD APIs
# ─────────────────────────────────────────────
class ClientCreateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request):
        org = request.organization
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "El nombre es obligatorio."}, status=400)

        client = Client(
            organization=org,
            name=name,
            email=data.get("email", "").strip(),
            phone=data.get("phone", "").strip(),
            notes=data.get("notes", "").strip(),
            source="manual",
            updated_by=request.user,
        )
        try:
            client.save()
        except Exception as e:
            if "unique" in str(e).lower():
                return JsonResponse({"error": "Ya existe un cliente con ese email o teléfono."}, status=400)
            raise
        return JsonResponse({"id": client.pk, "name": client.name})


class ClientUpdateAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "El nombre es obligatorio."}, status=400)

        client.name = name
        client.email = data.get("email", "").strip()
        client.phone = data.get("phone", "").strip()
        client.notes = data.get("notes", "").strip()
        client.updated_by = request.user
        try:
            client.save()
        except Exception as e:
            if "unique" in str(e).lower():
                return JsonResponse({"error": "Ya existe un cliente con ese email o teléfono."}, status=400)
            raise
        return JsonResponse({"id": client.pk, "name": client.name})


class ClientDeleteAPI(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def post(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)
        client.is_active = False
        client.updated_by = request.user
        client.save()
        return JsonResponse({"ok": True})


class ClientDetailAPI(LoginRequiredMixin, View):
    """GET single client data for profile modal."""

    def get(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)
        return JsonResponse({
            "id": client.pk,
            "name": client.name,
            "email": client.email,
            "phone": client.phone,
            "notes": client.notes,
            "source": client.source,
            "created_at": client.created_at.strftime("%d/%m/%Y"),
        })


class ClientNotesUpdateAPI(LoginRequiredMixin, View):
    """POST to update client notes from profile modal."""

    def post(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)
        client.notes = data.get("notes", "").strip()
        client.updated_by = request.user
        client.save()
        return JsonResponse({"ok": True})


# ─────────────────────────────────────────────
# Intervention history for profile modal (infinite scroll)
# ─────────────────────────────────────────────
class ClientInterventionHistoryAPI(LoginRequiredMixin, View):
    """
    Paginated intervention history for a client.
    IntersectionObserver-based infinite scroll, 30 per page.
    """
    PAGE_SIZE = 30

    def get(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)

        try:
            page = int(request.GET.get("page", 1))
        except (ValueError, TypeError):
            page = 1

        offset = (page - 1) * self.PAGE_SIZE
        qs = Intervencion.objects.filter(client=client).select_related(
            "barber__membership__user", "barbershop",
        ).prefetch_related(
            "servicios__servicio",
            "productos_usados__producto",
        ).order_by("-fecha")

        total = qs.count()
        items = qs[offset:offset + self.PAGE_SIZE]

        results = []
        for inv in items:
            servicios = list(inv.servicios.all())
            productos = list(inv.productos_usados.all())
            total_svc = sum(s.precio_cobrado for s in servicios)
            total_prod = sum(p.cantidad * p.precio_unitario for p in productos)
            total_inv = total_svc + total_prod
            fecha_local = timezone.localtime(inv.fecha) if inv.fecha else None

            results.append({
                "id": inv.pk,
                "fecha": fecha_local.strftime("%d/%m/%Y %H:%M") if fecha_local else "",
                "servicios": [s.servicio.name for s in servicios],
                "sucursal": str(inv.barbershop) if inv.barbershop else "",
                "gastos_fmt": f"${_format_money(total_inv)}",
                "estado": inv.estado,
                "estado_display": inv.get_estado_display(),
            })

        has_next = (offset + self.PAGE_SIZE) < total
        return JsonResponse({
            "results": results,
            "page": page,
            "has_next": has_next,
        })


# ─────────────────────────────────────────────
# Ficha Clínica CRUD
# ─────────────────────────────────────────────
class FichaClinicaAPI(LoginRequiredMixin, View):
    """GET / POST ficha clínica for a client."""

    def get(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)
        ficha = client.fichas_clinicas.first()
        if not ficha:
            return JsonResponse({"exists": False})
        return JsonResponse({
            "exists": True,
            "id": ficha.pk,
            "historia_clinica": ficha.historia_clinica,
            "recomendaciones": ficha.recomendaciones,
            "notas_medicas": ficha.notas_medicas,
            "datos_extra": ficha.datos_extra,
            "created_at": ficha.created_at.strftime("%d/%m/%Y %H:%M"),
            "updated_at": ficha.updated_at.strftime("%d/%m/%Y %H:%M"),
        })

    def post(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        ficha = client.fichas_clinicas.first()
        if ficha:
            ficha.historia_clinica = data.get("historia_clinica", "").strip()
            ficha.recomendaciones = data.get("recomendaciones", "").strip()
            ficha.notas_medicas = data.get("notas_medicas", "").strip()
            ficha.updated_by = request.user
            ficha.save()
        else:
            ficha = FichaClinica.objects.create(
                client=client,
                historia_clinica=data.get("historia_clinica", "").strip(),
                recomendaciones=data.get("recomendaciones", "").strip(),
                notas_medicas=data.get("notas_medicas", "").strip(),
                updated_by=request.user,
            )
        return JsonResponse({"ok": True, "id": ficha.pk})


class FichaClinicaPDFView(LoginRequiredMixin, View):
    """Generate and download a PDF of the ficha clínica."""

    def get(self, request, pk):
        org = request.organization
        client = get_object_or_404(Client, pk=pk, organization=org, is_active=True)
        ficha = client.fichas_clinicas.first()

        # Build HTML for PDF
        html_content = self._build_html(client, ficha)

        # Try WeasyPrint first, fall back to ReportLab
        try:
            return self._pdf_weasyprint(html_content, client)
        except ImportError:
            return self._pdf_reportlab(client, ficha)

    def _build_html(self, client, ficha):
        fecha = timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M")
        historia = ficha.historia_clinica if ficha else "Sin información"
        recomendaciones = ficha.recomendaciones if ficha else "Sin información"
        notas = ficha.notas_medicas if ficha else "Sin información"

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #333; margin: 40px; }}
        h1 {{ color: #ff2301; font-size: 24px; border-bottom: 2px solid #ff2301; padding-bottom: 8px; }}
        h2 {{ color: #555; font-size: 16px; margin-top: 24px; margin-bottom: 8px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
        .client-info {{ background: #f7f7f8; padding: 16px; border-radius: 8px; margin-bottom: 20px; }}
        .client-info p {{ margin: 4px 0; font-size: 14px; }}
        .section {{ margin-bottom: 20px; }}
        .section-content {{ background: #fafafa; padding: 12px; border-radius: 6px; border-left: 3px solid #ff2301; white-space: pre-wrap; font-size: 13px; line-height: 1.6; }}
        .footer {{ margin-top: 40px; text-align: center; color: #999; font-size: 11px; }}
    </style>
</head>
<body>
    <h1>Ficha Clínica – BarberSync</h1>
    <div class="client-info">
        <p><strong>Cliente:</strong> {client.name}</p>
        <p><strong>Email:</strong> {client.email or '—'}</p>
        <p><strong>Teléfono:</strong> {client.phone or '—'}</p>
        <p><strong>Fecha de generación:</strong> {fecha}</p>
    </div>
    <div class="section">
        <h2>Historia Clínica</h2>
        <div class="section-content">{historia}</div>
    </div>
    <div class="section">
        <h2>Recomendaciones</h2>
        <div class="section-content">{recomendaciones}</div>
    </div>
    <div class="section">
        <h2>Notas Médicas / Estéticas</h2>
        <div class="section-content">{notas}</div>
    </div>
    <div class="footer">
        Generado por BarberSync – {fecha}
    </div>
</body>
</html>"""

    def _pdf_weasyprint(self, html_content, client):
        from weasyprint import HTML
        pdf_bytes = HTML(string=html_content).write_pdf()
        buffer = io.BytesIO(pdf_bytes)
        safe_name = client.name.replace(" ", "_")[:30]
        return FileResponse(
            buffer,
            as_attachment=True,
            filename=f"ficha_clinica_{safe_name}.pdf",
            content_type="application/pdf",
        )

    def _pdf_reportlab(self, client, ficha):
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        brand_color = HexColor("#ff2301")

        title_style = ParagraphStyle("Title", parent=styles["Title"], textColor=brand_color, fontSize=20)
        heading_style = ParagraphStyle("H2", parent=styles["Heading2"], textColor=HexColor("#555555"), fontSize=14)
        body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=12, leading=16)

        elements = []
        elements.append(Paragraph(f"Ficha Clínica – {client.name}", title_style))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"<b>Email:</b> {client.email or '—'} | <b>Teléfono:</b> {client.phone or '—'}", body_style))
        elements.append(Spacer(1, 20))

        historia = ficha.historia_clinica if ficha else "Sin información"
        recomendaciones = ficha.recomendaciones if ficha else "Sin información"
        notas = ficha.notas_medicas if ficha else "Sin información"

        for title, content in [("Historia Clínica", historia), ("Recomendaciones", recomendaciones), ("Notas Médicas / Estéticas", notas)]:
            elements.append(Paragraph(title, heading_style))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(content.replace("\n", "<br/>"), body_style))
            elements.append(Spacer(1, 16))

        doc.build(elements)
        buffer.seek(0)
        safe_name = client.name.replace(" ", "_")[:30]
        return FileResponse(
            buffer,
            as_attachment=True,
            filename=f"ficha_clinica_{safe_name}.pdf",
            content_type="application/pdf",
        )


# ─────────────────────────────────────────────
# Search API (used by other modules for autocomplete)
# ─────────────────────────────────────────────
class ClientSearchAPI(View):
    """
    Quick search API for autocomplete in appointment creation forms.
    GET /app/clients/api/search/?q=Juan
    """

    def get(self, request):
        org = getattr(request, "organization", None)
        if org is None:
            return JsonResponse([], safe=False)

        q = request.GET.get("q", "").strip()
        if len(q) < 2:
            return JsonResponse([], safe=False)

        clients = Client.objects.filter(
            organization=org,
            is_active=True,
        ).filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
        )[:10]

        data = [
            {"id": c.pk, "name": c.name, "email": c.email, "phone": c.phone}
            for c in clients
        ]
        return JsonResponse(data, safe=False)

import locale
import json
from django.views import generic
from django.shortcuts import redirect
from django.http import JsonResponse
from .models import *
from psycopg2.extras import RealDictCursor
from django.views import View
from django.db import connection
from datetime import datetime,timedelta
from django.middleware.csrf import get_token
import logging
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import (
    LoginRequiredMixin,
    PermissionRequiredMixin
)
from django.contrib.auth import get_user_model,logout, login



class ScheduleQueryApi(View):

    ALLOWED_IP = '127.0.0.1'

    query = """
    SELECT
        s.nombre_servicio,
        s.duracion_servicio,
        s.precio,
        sb."idBarber",
        ib."idIntervencion",
        ib.inicio_programado,
        ib."idCliente",
        ib."idEstado",
        ib.inicio_programado + (s.duracion_servicio * INTERVAL '1 minute') AS fin_estimado
    FROM
        "Specify"."Servicios" AS s
    JOIN
        "Specify"."servicios_barber" sb ON s."idService" = sb."idService"
    JOIN
        "Specify"."intervenciones_barber" ib ON sb."idServicioBarber" = ib."idServicioBarber"
    WHERE
        ib."idEstado" = 1
        AND ib.inicio_programado > NOW()::timestamp
        AND ib.inicio_programado <= NOW() + INTERVAL '7 days';
    """

    query_anomalias = """
    SELECT * FROM "Specify".anomalias_horario
    WHERE evento_horario = 'PermisoSalida'
        AND fecha_inicio > NOW()::timestamp
    """

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        # Aplica el decorador a todos los métodos HTTP de la vista
        return super().dispatch(*args, **kwargs)

    def get(self, request):

        client_ip = request.META.get('REMOTE_ADDR')
        if client_ip != self.ALLOWED_IP:
            logger.warning(f"Acceso denegado desde la IP {client_ip} en GET")
            return JsonResponse({'error': 'Forbidden'}, status=403)
        
        barberos_list = list(Barberos.objects.filter(is_active=True).values_list('idBarber', 'nombre_barbero'))
        servicios_barber_list = list(ServiciosBarber.objects.all())
        Services = list(Servicios.objects.values())

        events = []
        available = set()
        conn = connection.connection

        # Obtener eventos de la base de datos
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(self.query)
            resultados = cursor.fetchall()

        # Obtener anomalías de horarios
        resultados_anomalias = list(AnomaliasHorario.objects.filter(evento_horario='PermisoSalida', fecha_inicio__gt=datetime.now()).values())

        # Procesar anomalías de horarios
        for row in resultados_anomalias:
            events.append(
                {
                    'idBarber': row['barber_id_id'],
                    'fecha_inicio': row['fecha_inicio'],
                    'fecha_fin': row['fecha_fin']
                }
            )

        # Procesar los resultados de los eventos
        for row in resultados:
            events.append(
                {
                    'idBarber': row['idBarber'],
                    'fecha_inicio': row['inicio_programado'],
                    'fecha_fin': row['fin_estimado']
                }
            )

        # Horarios de trabajo estándar
        
        now = datetime.now().replace(tzinfo=None, second=0, microsecond=0)
        hora_fin = now.replace(tzinfo=None, hour=20, minute=0, second=0, microsecond=0)
        if now >= hora_fin or (now + timedelta(hours=1)) >= hora_fin:
            hora_inicio = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            hora_fin = (now + timedelta(days=1)).replace(tzinfo=None, hour=20, minute=0, second=0, microsecond=0)
        else: 
            hora_inicio = (now + timedelta(hours=1)).replace(minute= 0 if now.minute > 30 else 30, second=0, microsecond=0)
        
        #hora_inicio = datetime.now().replace(tzinfo=None, hour=8, minute=0, second=0, microsecond=0)

        #print(f'now: {now}\nhora_inicio: {hora_inicio}\nhora_fin: {hora_fin}')
       

        # Agrupar eventos por idBarber
        eventos_por_barber = {}
        for evento in events:
            if evento['idBarber'] not in eventos_por_barber:
                eventos_por_barber[evento['idBarber']] = []
            eventos_por_barber[evento['idBarber']].append(evento)

        # Para cada barbero, calculamos los espacios libres
        Barber_schedule = []  # Lista para almacenar los horarios por barbero

        for idBarber,nombre_barbero in barberos_list:
            servicios_para_barber = [servicio for servicio in servicios_barber_list if servicio.barber_id.idBarber == idBarber]
            eventos = eventos_por_barber.get(idBarber, [])
            eventos.sort(key=lambda x: x["fecha_inicio"].replace(tzinfo=None))

            espacios_libres = []
            hora_anterior = hora_inicio

            # Calcular los espacios libres para cada barbero
            for evento in eventos:
                if evento["fecha_inicio"].tzinfo is not None:
                    evento["fecha_inicio"] = evento["fecha_inicio"].replace(tzinfo=None)
                if evento["fecha_fin"].tzinfo is not None:
                    evento["fecha_fin"] = evento["fecha_fin"].replace(tzinfo=None)

                if evento["fecha_fin"].hour > 20:
                    evento["fecha_fin"] = evento["fecha_fin"].replace(hour=20, minute=0, second=0)

                if evento["fecha_fin"].date() != evento["fecha_inicio"].date():
                    evento["fecha_fin"] = evento["fecha_fin"].replace(day=evento["fecha_inicio"].day)

                if evento["fecha_inicio"] > hora_anterior and evento["fecha_inicio"].date() == hora_anterior.date():
                    espacios_libres.append((hora_anterior, evento["fecha_inicio"], idBarber))
                    available.add(evento["fecha_inicio"].replace(hour=0, minute=0))  # Agregar la fecha al conjunto de disponibles
                elif evento["fecha_inicio"] > hora_anterior and evento["fecha_inicio"].date() != hora_anterior.date():
                    hora_fin_ = hora_fin.replace(year=hora_anterior.year, month=hora_anterior.month, day=hora_anterior.day)
                    hora_inicio_ = hora_inicio.replace(year=evento["fecha_inicio"].year, month=evento["fecha_inicio"].month, day=evento["fecha_inicio"].day)
                    
                    if hora_anterior != hora_fin_:
                        espacios_libres.append((hora_anterior, hora_fin_, idBarber))
                        available.add(hora_anterior.replace(hour=0, minute=0))  # Agregar la fecha al conjunto de disponibles

                    if hora_inicio_ != evento["fecha_inicio"]:
                        espacios_libres.append((hora_inicio_, evento["fecha_inicio"], idBarber))
                        available.add(hora_inicio_.replace(hour=0, minute=0))  # Agregar la fecha al conjunto de disponibles

                hora_anterior = max(hora_anterior, evento["fecha_fin"])

            if hora_anterior < hora_fin:
                espacios_libres.append((hora_anterior, hora_fin, idBarber))
                available.add(hora_anterior.replace(hour=0, minute=0))  # Agregar la fecha al conjunto de disponibles

            # Agregar intervalos completos para los siguientes días (saltando domingos)
            dias_extra = 7
            for i in range(1, dias_extra + 1):
                dia_adicional = hora_inicio + timedelta(days=i)

                if dia_adicional.weekday() == 6:
                    continue

                hora_inicio_dia = datetime(dia_adicional.year, dia_adicional.month, dia_adicional.day, 8, 0)
                hora_fin_dia = datetime(dia_adicional.year, dia_adicional.month, dia_adicional.day, 20, 0)

                evento_dia = [evento for evento in eventos if evento["fecha_inicio"].date() == dia_adicional.date()]
                if not evento_dia:
                    espacios_libres.append((hora_inicio_dia, hora_fin_dia, idBarber))
                    available.add(dia_adicional.replace(hour=0, minute=0))  # Agregar la fecha al conjunto de disponibles

            # Agregar el intervalo hasta las 20:00 si no se cubre todo el horario
            ultimo_dia = hora_anterior.date()
            if hora_anterior < datetime(ultimo_dia.year, ultimo_dia.month, ultimo_dia.day, 20, 0):
                if hora_anterior != hora_inicio:
                    espacios_libres.append((hora_anterior, datetime(ultimo_dia.year, ultimo_dia.month, ultimo_dia.day, 20, 0), idBarber))
                    available.add(hora_anterior.replace(hour=0, minute=0))  # Agregar la fecha al conjunto de disponibles

            # Almacenar los horarios disponibles para este barbero
            Barber_schedule.append({
                "idBarber": idBarber,
                "nombre_barbero" : nombre_barbero,
                "services" : [
                    {   
                        "numerate" : idx,
                        "idServicioBarber" : sevicio.idServicioBarber,
                        "idService" : sevicio.servicio_id.idService,
                        "nombreServicio" : sevicio.servicio_id.nombre_servicio,
                        "precio" : sevicio.servicio_id.precio,
                        "duracion" : sevicio.servicio_id.duracion_servicio
                    }
                    for idx,sevicio in enumerate(servicios_para_barber, 1)
                ],
                "schedule": [
                    {
                        "fecha_inicio": inicio,
                        "fecha_fin": fin
                    }
                    for inicio, fin, _ in espacios_libres
                ]
            })

        # Convertimos el conjunto de fechas a una lista de fechas únicas
        available = list(available)
        available.sort()
        available_list = []
        for idx, avail in enumerate(available, 1):
            available_list.append({
                'idFecha': idx,
                'datetime': avail,
                'text': avail.strftime("%A %d de %B %Y").capitalize().replace('ã¡','a').replace('ã©','e')
            })

        # Devolver el resultado con los horarios por barbero y las fechas disponibles
        return JsonResponse({"message": "Success", "Barber": Barber_schedule,"Services" : Services, "available": available_list})
    
    def post(self, request):
        client_ip = request.META.get('REMOTE_ADDR')

        try:
            data = json.loads(request.body)  # Utiliza request.body para obtener los datos JSON
        except json.JSONDecodeError:
            return JsonResponse({"message": "Invalid JSON"}, status=400)
        
        if data:
            try:
                with transaction.atomic():
                    try:
                        cliente = Clientes.objects.get(telefono=data['from'])
                    except:
                        cliente = Clientes.objects.create(
                            nombre_cliente = data['clientName'],
                            telefono = data['from'],
                            updated_by = User.objects.get(id=1),
                        )


                    fecha = data['fechaSeleccionada']
                    hora = data['turno']["inicioEstimado"]
                    fecha_completa = fecha.replace('T00:00:00',f'T{hora}:00')
                    inicio_programado = datetime.fromisoformat(fecha_completa)

                    existe_intervencion = IntervencionesBarber.objects.filter(
                        inicio_programado=inicio_programado,
                        servicio_barber_id=data['idServicioBarber'],
                        id_estado_servicio=1
                    ).exists()

                    if existe_intervencion:
                        return JsonResponse({"message": "Turno ya agendado"}, status=400)
                    else:
                        IntervencionesBarber.objects.create(
                            servicio_barber_id = ServiciosBarber.objects.get(idServicioBarber=data['idServicioBarber']),
                            cliente_id = cliente,
                            inicio_programado = inicio_programado,
                            id_estado_servicio = EstadosIntervenciones.objects.get(idEstado=1),
                            updated_by = User.objects.get(id=1) #TODO Mejorar la seguridad,
                        )
                        
                        """
                        para mejorar la seguridad, podria mandar el id del Usuario asignado al ChatBot con una codificacion
                        """   
                        return JsonResponse({"message": "Post request successful"})
                
            except Exception as e:
                logging.error("Error en la solicitud, se ha revertido la transacción.", e)
                return JsonResponse({"message": "Error en la solicitud, se ha revertido la transacción."}, status=500)
                

        else:
            return JsonResponse({"message": "Invalid JSON No data"}, status=400)
        
class QueryShift(View):
    @csrf_exempt
    def dispatch(self, *args, **kwargs): #TODO Mejorar seguridad en los metodos dispatch, hacer validacion de ip local
        # Aplica el decorador a todos los métodos HTTP de la vista
        return super().dispatch(*args, **kwargs)
    
    def get(self, request, phone, *args, **kwargs):
        try:
            turnos = IntervencionesBarber.objects.filter(
                cliente_id = Clientes.objects.get(telefono=phone),
                id_estado_servicio = EstadosIntervenciones.objects.get(idEstado=1),
                inicio_programado__gt = datetime.now()
            ).select_related('cliente_id', 'servicio_barber_id', 'id_estado_servicio')
        except Clientes.DoesNotExist:
            return JsonResponse({"message": "Success", "turnos" : []}, status=200)
        except Exception as e:
            logging.error(f"Error inesperado en la consulta de turnos: {str(e)}", exc_info=True)
            return {"message": "Error en el sistema"}
            

        turnos_list = [
            {
                "idIntervencion": turno.idIntervencion,
                "cliente": turno.cliente_id.nombre_cliente,  # Cambia 'nombre' por el campo real del modelo
                "servicio": turno.servicio_barber_id.servicio_id.nombre_servicio,  # Cambia 'nombre' por el campo real del servicio
                "barbero": turno.servicio_barber_id.barber_id.nombre_barbero,
                "inicio_programado": turno.inicio_programado,
                "fecha_creacion": turno.fecha_creacion,
            }
            for turno in turnos
        ]
        return JsonResponse({"message": "Success",
                             "turnos" : turnos_list}, status=200)
    
    def post(self, request):
        try:
            data = json.loads(request.body)  # Utiliza request.body para obtener los datos JSON
        except json.JSONDecodeError:
            return JsonResponse({"message": "Invalid JSON"}, status=400)
        
        if data:
            turnoSeleccionado = IntervencionesBarber.objects.get(idIntervencion=data['idIntervencion'])

            if turnoSeleccionado:
                try:
                    turnoSeleccionado.id_estado_servicio = EstadosIntervenciones.objects.get(idEstado=3)
                    turnoSeleccionado.save()
                    return JsonResponse({"message": "Post request successful"}, status=200)
                except:
                    return JsonResponse({"message": "ERROR AL ACTUALIZAR REGISTRO"}, status=400)
            
            return JsonResponse({"message": "Post request invalid"}, status=400)

def event_api(request, idBarber):
    events = IntervencionesBarber.objects.filter(servicio_barber_id__barber_id=idBarber,id_estado_servicio__in=[1, 2])

    events_json = [
        {
            "id": event.idIntervencion,
            "title": f'{event.cliente_id.nombre_cliente}',# \nServicio: {event.servicio_barber_id.servicio_id.nombre_servicio}'f'{event.id_estado_servicio.estado} con {event.cliente_id.nombre_cliente}',
            "start": event.inicio_programado.isoformat(),
            "end": (event.inicio_programado + timedelta(minutes=event.servicio_barber_id.servicio_id.duracion_servicio)).isoformat() if event.servicio_barber_id.servicio_id.duracion_servicio else event.inicio_programado.isoformat(),
            "description": {
                "nombre_cliente" : event.cliente_id.nombre_cliente,
                "telefono" : event.cliente_id.telefono,
                "email": event.cliente_id.email,
                "estado" : event.id_estado_servicio.estado,
                "nombre_servicio" : event.servicio_barber_id.servicio_id.nombre_servicio,
                "duracion" : event.servicio_barber_id.servicio_id.duracion_servicio,
                "precio" : event.servicio_barber_id.servicio_id.precio,
                "nombre_barbero" : event.servicio_barber_id.barber_id.nombre_barbero,
                "inicio_programado" : event.inicio_programado, #.strftime("%I:%M %p"),
                "fin_estimado": (event.inicio_programado + timedelta(minutes=event.servicio_barber_id.servicio_id.duracion_servicio)) if event.servicio_barber_id.servicio_id.duracion_servicio else event.inicio_programado,
            }
        }
        for event in events
    ]

    return JsonResponse(events_json, safe=False)
from django.db import models
from django.core.validators import MinValueValidator, RegexValidator
from datetime import datetime
from .choices import eventos_horario_choices
from django.contrib.auth.models import User
from django.utils import timezone

# Create your models here.

def save_auditoria(self,old_object,es_creacion):
    # Definir la acción de acuerdo a si es creación o actualización
        evento = f"{self._meta.db_table}.Created" if es_creacion else f"{self._meta.db_table}.Updated"
        
        # Generar la descripción de los campos modificados (si es una actualización)
        descripcion = ""
        if not es_creacion:
            # Compara los valores antiguos y nuevos para generar la descripción
            cambios = {'before' : {}, 'after' : {}}
            for field in self._meta.fields:
                old_value = getattr(old_object, field.name, None)
                new_value = getattr(self, field.name, None)

                if old_value != new_value:
                    if field.name not in ['updated_at','updated_by']:
                        cambios['before'][field.name] = old_value
                        cambios['after'][field.name] = new_value
            descripcion = f'"Campos modificados:" { cambios }'

            if len(cambios['after']) > 0:
                Auditoria.objects.create(
                    evento=evento,
                    tabla=self._meta.db_table,
                    objeto=self.pk,
                    descripcion=descripcion,
                    idUsuario= self.updated_by.id if self.updated_by else 1,
                    created_at=timezone.now(),
                    updated_at=timezone.now()
                )
        else:
            Auditoria.objects.create(
                    evento=evento,
                    tabla=self._meta.db_table,
                    objeto=self.pk,
                    descripcion=f"Nuevo Registro con id: {self.pk}",
                    idUsuario= self.updated_by.id if self.updated_by else 1,
                    created_at=timezone.now(),
                    updated_at=timezone.now()
                )

class Auditoria(models.Model):
    idAuditoria = models.AutoField(db_column='idAuditoria',primary_key=True)
    evento = models.CharField(max_length=45)
    tabla = models.CharField(max_length=40)
    objeto = models.IntegerField(blank=True,null=True)
    descripcion=models.TextField()
    idUsuario = models.IntegerField(blank=True,null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=False,null=False,auto_now=True)

    class Meta:
        verbose_name='Auditoria'
        verbose_name_plural='Auditoria'
        db_table = '"Specify"."Auditoria"'

class Servicios(models.Model):
    idService = models.AutoField(db_column='idService',primary_key=True)
    nombre_servicio = models.CharField(max_length=30)
    descripcion=models.TextField()
    duracion_servicio = models.IntegerField(validators=[
            MinValueValidator(0),  # Mínimo 0
        ])
    precio = models.IntegerField()

    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=False,null=False,auto_now=True)

    def __str__(self):
        return f'{self.nombre_servicio} ({self.idService})'

    class Meta:
        verbose_name='Servicios'
        verbose_name_plural='Servicios'
        db_table = '"Specify"."Servicios"'

    def save(self, *args, **kwargs):
        es_creacion = self.pk is None  # Si no tiene pk, es creación (no tiene id)
        if not es_creacion:
            old_object = self.__class__.objects.get(pk=self.pk)
        else:
            old_object = None
        
        # Guardar el objeto primero
        super().save(*args, **kwargs)

        save_auditoria(self,old_object,es_creacion)

class Barberos(models.Model):
    idBarber = models.AutoField(db_column='idBarber',primary_key=True)
    nombre_barbero = models.CharField(max_length=100)
    telefono =  models.CharField(
        max_length=15, 
        validators=[
            RegexValidator(
                regex=r'^\+?\d{7,15}$',
                message='El número de teléfono debe contener entre 7 y 15 dígitos y puede comenzar con "+"'
            )
        ],null=False,blank=False)
    email = models.CharField(max_length=100,null=True,blank=True)
    redes_sociales = models.TextField(null=True,blank=True)
    fecha_registro = models.DateTimeField(auto_created=True,default=datetime.now())
    is_active = models.BooleanField(auto_created=True,default=True)

    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=False,null=False,auto_now=True)

    def __str__(self):
        return f'{self.nombre_barbero} ({self.idBarber})'

    class Meta:
        verbose_name='Barberos'
        verbose_name_plural='Barberos'
        db_table = '"Specify"."Barberos"'

    def save(self, *args, **kwargs):
        es_creacion = self.pk is None  # Si no tiene pk, es creación (no tiene id)
        if not es_creacion:
            old_object = self.__class__.objects.get(pk=self.pk)
        else:
            old_object = None
        
        # Guardar el objeto primero
        super().save(*args, **kwargs)

        save_auditoria(self,old_object,es_creacion)

class Clientes(models.Model):
    idCliente = models.AutoField(db_column='idCliente',primary_key=True)
    nombre_cliente = models.CharField(max_length=100)
    telefono =  models.CharField(
        max_length=15, 
        validators=[
            RegexValidator(
                regex=r'^\+?\d{7,15}$',
                message='El número de teléfono debe contener entre 7 y 15 dígitos y puede comenzar con "+"'
            )
        ],
        null=True,
        blank=True,
        unique=True)
    email = models.CharField(max_length=100,null=True,blank=True)
    redes_sociales = models.TextField(null=True,blank=True)
    fecha_registro = models.DateTimeField(auto_created=True,default=datetime.now())

    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=False,null=False,auto_now=True)

    def __str__(self):
        return f'{self.nombre_cliente} ({self.idCliente})'

    class Meta:
        verbose_name='Clientes'
        verbose_name_plural='Clientes'
        db_table = '"Specify"."Clientes"'

    def save(self, *args, **kwargs):
        es_creacion = self.pk is None  # Si no tiene pk, es creación (no tiene id)
        print('es_creacion',es_creacion)
        if not es_creacion:
            old_object = self.__class__.objects.get(pk=self.pk)
        else:
            old_object = None
        
        # Guardar el objeto primero
        super().save(*args, **kwargs)

        save_auditoria(self,old_object,es_creacion)



class ServiciosBarber(models.Model):
    idServicioBarber = models.AutoField(db_column='idServicioBarber',primary_key=True)
    barber_id = models.ForeignKey(
        Barberos,
        on_delete=models.CASCADE,
        db_column='idBarber',
        related_name='servicios_asociados')
    servicio_id=models.ForeignKey(
        Servicios,
        on_delete=models.CASCADE,
        db_column='idService',
        related_name='barberos_asociados'
    )

    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=False,null=False,auto_now=True)

    def __str__(self):
        return f'{self.barber_id.nombre_barbero} : ({self.servicio_id.nombre_servicio})'
    
    class Meta:
        verbose_name='Servicios Barber'
        verbose_name_plural='Servicios Barber'
        db_table = '"Specify"."servicios_barber"'

    def save(self, *args, **kwargs):
        es_creacion = self.pk is None  # Si no tiene pk, es creación (no tiene id)
        if not es_creacion:
            old_object = self.__class__.objects.get(pk=self.pk)
        else:
            old_object = None
        
        # Guardar el objeto primero
        super().save(*args, **kwargs)

        save_auditoria(self,old_object,es_creacion)

class AnomaliasHorario(models.Model):
    id = models.AutoField(primary_key=True)
    evento_horario = models.CharField(
        max_length=25,
        choices=eventos_horario_choices,
        null=False
    )
    descripcion = models.TextField(null=False)
    fecha_inicio = models.DateTimeField(null=False)
    fecha_fin = models.DateTimeField(null=False)
    barber_id = models.ForeignKey(
        Barberos,
        on_delete=models.CASCADE,
        db_column='idBarber',
        related_name='barbero_horario')
    
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=False,null=False,auto_now=True)

    class Meta:
        verbose_name='Anomalias Horario'
        verbose_name_plural='Anomalias Horario'
        db_table = '"Specify"."anomalias_horario"'

    def save(self, *args, **kwargs):
        es_creacion = self.pk is None  # Si no tiene pk, es creación (no tiene id)
        if not es_creacion:
            old_object = self.__class__.objects.get(pk=self.pk)
        else:
            old_object = None
        
        # Guardar el objeto primero
        super().save(*args, **kwargs)

        save_auditoria(self,old_object,es_creacion)

class EstadosIntervenciones(models.Model):
    idEstado = models.AutoField(db_column='idEstado',primary_key=True)
    estado = models.CharField(max_length=25)
    descripcion = models.TextField()

    def __str__(self):
        return f'{self.estado} ({self.idEstado})'

    class Meta:
        verbose_name='Estados Intervenciones'
        verbose_name_plural='Estados Intervenciones'
        db_table = '"Specify"."estados_intervenciones"'

class IntervencionesBarber(models.Model): #TODO agregar precio historico, por si se actualiza el precio del serviciuo no se muevan las metricas
    idIntervencion = models.AutoField(db_column='idIntervencion',primary_key=True)
    servicio_barber_id = models.ForeignKey(
        ServiciosBarber,
        on_delete=models.CASCADE,
        db_column='idServicioBarber',
        related_name='servicios_intervencion')
    cliente_id=models.ForeignKey(
        Clientes,
        on_delete=models.CASCADE,
        db_column='idCliente',
        related_name='cliente_intervencion'
    )
    fecha_creacion = models.DateTimeField(auto_created=True,default=datetime.now())
    inicio_programado = models.DateTimeField(blank=False,null=False)
    id_estado_servicio = models.ForeignKey(
        EstadosIntervenciones,
        on_delete=models.CASCADE,
        db_column='idEstado',
        related_name='estado_intervencion')
    
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(blank=False,null=False,auto_now=True)

    class Meta:
        verbose_name='Intervenciones'
        verbose_name_plural='Intervenciones'
        db_table = '"Specify"."intervenciones_barber"'

    def save(self, *args, **kwargs):
        es_creacion = self.pk is None
        if not es_creacion:
            old_object = self.__class__.objects.get(pk=self.pk)
        else:
            old_object = None
        
        # Guardar el objeto primero
        super().save(*args, **kwargs)

        save_auditoria(self,old_object,es_creacion)
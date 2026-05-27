

from django.db import connection
from models import Barberos
from django.contrib.auth.models import User

# 1. Alter table
with connection.cursor() as cursor:
    try:
        cursor.execute('ALTER TABLE "Specify"."Barberos" ADD COLUMN "idUsuario" integer NULL;')
        print("Columna idUsuario agregada")
    except Exception as e:
        print("La columna idUsuario posiblemente ya existe:", e)

# 2. Migrate data
barberos = Barberos.objects.all()
migrados = 0
for b in barberos:
    # Try to find a user by email
    user = None
    if b.email:
        user = User.objects.filter(email=b.email).first()
    
    # If not found by email, try by name
    if not user and b.nombre_barbero:
        # Simple match
        user = User.objects.filter(first_name=b.nombre_barbero).first()
    
    if user:
        b.user = user
        b.save()
        migrados += 1
        print(f"Barbero {b.idBarber} ({b.nombre_barbero}) enlazado al usuario {user.id}")
    else:
        print(f"No se encontró usuario para Barbero {b.idBarber} ({b.nombre_barbero})")

print(f"Migración de datos completa. Migrados: {migrados}/{barberos.count()}")

# 3. Drop columns
with connection.cursor() as cursor:
    try:
        cursor.execute('ALTER TABLE "Specify"."Barberos" DROP COLUMN "nombre_barbero";')
        cursor.execute('ALTER TABLE "Specify"."Barberos" DROP COLUMN "telefono";')
        cursor.execute('ALTER TABLE "Specify"."Barberos" DROP COLUMN "email";')
        print("Columnas antiguas eliminadas")
    except Exception as e:
        print("Error eliminando columnas (posiblemente ya no existen):", e)

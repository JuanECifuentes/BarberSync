class Usuario:
    def __init__(self, nombre: str, altura: float = 0, apellido: str = "", edad: int = 0):
        self.nombre = nombre
        self.altura = altura
        self.apellido = apellido
        self.edad = edad

    def mostrar_altura(self):
        return f"{self.nombre} mide {self.altura} cm"

    def mostrar_apellido(self):
        return f"{self.nombre} {self.apellido}"

    def mostrar_edad(self):
        return f"{self.nombre} tiene {self.edad} años"

def saludar(usuario: Usuario):
    return f"Hola {usuario.nombre}"


class Perro:
    def __init__(self, nombre: str, raza: str = "", edad: int = 0, peso: float = 0):
        self.nombre = nombre
        self.raza = raza
        self.edad = edad
        self.peso = peso

    def ladrar(self):
        return f"{self.nombre} dice: ¡Guau!"

    def informacion(self):
        return f"{self.nombre} - {self.raza}, {self.edad} años, {self.peso} kg"


class Gato:
    def __init__(self, nombre: str, raza: str = "", edad: int = 0, peso: float = 0):
        self.nombre = nombre
        self.raza = raza
        self.edad = edad
        self.peso = peso

    def maullar(self):
        return f"{self.nombre} dice: ¡Miau!"

    def informacion(self):
        return f"{self.nombre} - {self.raza}, {self.edad} años, {self.peso} kg"

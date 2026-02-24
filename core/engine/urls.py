from django.urls import path
from .views import health_check, generate_kit, regenerate_section

urlpatterns = [
    path("health/", health_check),
    path("generate/", generate_kit),
    path("regenerate/", regenerate_section),
]
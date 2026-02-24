from django.urls import path
from .views import health_check, generate_kit, regenerate_section, export_kit, recent_kits, kit_detail

urlpatterns = [
    path("health/", health_check),
    path("generate/", generate_kit),
    path("regenerate/", regenerate_section),
    path("export/", export_kit),

    # History APIs
    path("kits/recent/", recent_kits),
    path("kits/<int:kit_id>/", kit_detail),
]
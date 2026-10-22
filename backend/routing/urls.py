from django.urls import path

from routing import views

urlpatterns = [
    path("health", views.health),
    path("geocode", views.geocode),
    path("plan", views.plan),
    path("heatmap", views.heatmap),
]

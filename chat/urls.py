from django.urls import path
from chat import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/chat", views.api_chat, name="api_chat"),
    path("api/update-db", views.api_update_db, name="api_update_db"),
    path("api/db-meta", views.api_db_meta, name="api_db_meta"),
]

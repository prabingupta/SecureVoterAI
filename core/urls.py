# core/urls.py

from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    #  Pages 
    path('',                    views.index,                  name='index'),
    path('register/',           views.register_view,          name='register'),
    path('login/',              views.login_view,             name='login'),
    path('logout/',             views.logout_view,            name='logout'),
    path('face-verify/',        views.face_verify_view,       name='face_verify'),
    path('re-register-face/',   views.re_register_face_view,  name='re_register_face'),

    # AJAX / face API 
    path('face-verify/api/',            views.face_verify_api,         name='face_verify_api'),
    path('api/liveness-challenges/',    views.get_liveness_challenges, name='liveness_challenges'),

    #  JWT REST API 
    path('api/register/',   views.register_api,  name='register_api'),
    path('api/login/',      views.login_api,      name='login_api'),
]
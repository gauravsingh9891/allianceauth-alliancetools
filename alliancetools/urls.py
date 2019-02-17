from django.conf.urls import url
from django.urls import path

from . import views

app_name = 'alliancetools'

urlpatterns = [
    url(r'^$', views.dashboard, name='dashboard'),
    url(r'^structures/$', views.structures, name='structures'),
    url(r'^structure/(?P<structure_id>(\d)*)/$', views.structure, name='structure'),
    url(r'^addchar/$', views.alliancetools_add_char, name='add_char'),
]

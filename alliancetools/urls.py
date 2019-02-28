from django.conf.urls import url
from django.urls import path

from . import views

app_name = 'alliancetools'

urlpatterns = [
    url(r'^$', views.dashboard, name='dashboard'),
    url(r'^structures/$', views.structures, name='structures'),
    url(r'^structure/(?P<structure_id>(\d)*)/$', views.structure, name='structure'),
    url(r'^addchar/$', views.alliancetools_add_char, name='add_char'),
    url(r'^jobs/$', views.jobs_board, name='jobs_board'),
    url(r'^add_job/$', views.add_job, name='add_job'),
    url(r'^add_comment/(?P<job_id>(\d)*)/$', views.add_comment, name='add_comment'),
    url(r'^edit_job/(?P<job_id>(\d)*)/$', views.edit_job, name='edit_job'),
    url(r'^audit_log/(?P<job_id>(\d)*)/$', views.audit_log, name='audit_log'),
    url(r'^mark_complete/(?P<job_id>(\d)*)/$', views.mark_complete, name='mark_complete'),
]

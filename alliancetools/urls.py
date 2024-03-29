from django.conf.urls import url
from django.urls import path

from . import views

app_name = 'alliancetools'

urlpatterns = [
    url(r'^$', views.dashboard, name='dashboard'),
    url(r'^structures/$', views.structures, name='structures'),
    url(r'^fuel/$', views.fuel_levels, name='fuel'),
    url(r'^pocos/$', views.pocos, name='pocos'),
    url(r'^txfr/$', views.str_txfr, name='txfr'),
    url(r'^str_txfr/$', views.str_txfrs, name='str_txfr'),
    url(r'^ignore_structure/(?P<structure_id>(\d)*)/$', views.ignore_structure, name='ignore_structure'),
    url(r'^mark_txfr_complete/(?P<structure_id>(\d)*)/$', views.mark_txfr_complete, name='mark_txfr_complete'),
    url(r'^mark_txfr_uncomplete/(?P<structure_id>(\d)*)/$', views.mark_txfr_uncomplete, name='mark_txfr_uncomplete'),
    url(r'^structure/(?P<structure_id>(\d)*)/$', views.structure, name='structure'),
    url(r'^do_eve_prasial/(?P<structure_id>(\d)*)/$', views.do_eve_prasial, name='do_eve_prasial'),
    url(r'^addchar/$', views.alliancetools_add_char, name='add_char'),
    url(r'^addpoco/$', views.alliancetools_add_poco, name='add_poco'),
    url(r'^addmoons/$', views.alliancetools_add_moons, name='add_moons'),
    url(r'^addcontacts/$', views.alliancetools_add_contacts, name='add_contacts'),
    url(r'^addstruct/$', views.alliancetools_add_structures, name='add_structs'),
    url(r'^jobs/$', views.jobs_board, name='jobs_board'),
    url(r'^moons/$', views.extractions, name='moons'),
    url(r'^observers/(?P<corp_id>(\d)*)/(?P<month>(\d)*)/(?P<year>(\d)*)/$', views.observers, name='observers'),
    url(r'^observers/(?P<corp_id>(\d)*)/$', views.observers, name='observers'),
    url(r'^observers/$', views.observers, name='observers'),
    url(r'^timers/$', views.structure_timers, name='timers'),
    url(r'^contracts/$', views.view_contracts, name='contracts'),
    url(r'^contacts/$', views.view_contacts, name='contacts'),
    url(r'^add_job/$', views.add_job, name='add_job'),
    url(r'^add_comment/(?P<job_id>(\d)*)/$', views.add_comment, name='add_comment'),
    url(r'^edit_job/(?P<job_id>(\d)*)/$', views.edit_job, name='edit_job'),
    url(r'^audit_log/(?P<job_id>(\d)*)/$', views.audit_log, name='audit_log'),
    url(r'^mark_complete/(?P<job_id>(\d)*)/$', views.mark_complete, name='mark_complete'),
    url(r'^input_json_api/$', views.input_json_api, name='input_json_api'),
]

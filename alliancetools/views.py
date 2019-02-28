import logging
import datetime
import json

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib import messages
from esi.decorators import token_required
from allianceauth.eveonline.models import EveCharacter
from allianceauth.authentication.models import UserProfile
from django.db import IntegrityError
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import PermissionDenied

from .models import AllianceToolCharacter, Structure, CorpAsset, AllianceToolJob, AllianceToolJobComment
from .forms import AddJob, AddComment, EditJob
from easyaudit.models import CRUDEvent

CORP_REQUIRED_SCOPES = ['esi-characters.read_notifications.v1',
                        'esi-assets.read_corporation_assets.v1',
                        'esi-characters.read_corporation_roles.v1',
                        'esi-wallet.read_corporation_wallets.v1',
                        'esi-corporations.read_structures.v1',
                        'esi-universe.read_structures.v1']


@login_required
@permission_required('alliancetools.admin_alliance_tools')
def dashboard(request):
    try:
        main_characters = AllianceToolCharacter.objects.all()

        context = {
            'alts': main_characters,
            'add_tokens' : request.user.has_perm('alliancetools.admin_alliance_tools')
        }
        return render(request, 'alliancetools/dashboard.html', context=context)

    except:
        logging.exception("message")

    return render(request, 'alliancetools/dashboard.html')


@login_required
@permission_required('alliancetools.add_alliancetooljobcomment')
def jobs_board(request):
    try:
        jobs_open = AllianceToolJob.objects.filter(completed__isnull=True)
        jobs_closed = AllianceToolJob.objects.filter(completed__isnull=False).order_by('-completed')[:10]

        context = {
            'jobs': jobs_open,
            'closed': jobs_closed,
        }
        return render(request, 'alliancetools/jobs.html', context=context)

    except:
        logging.exception("message")

    return render(request, 'alliancetools/jobs.html')


@login_required
@permission_required('alliancetools.admin_alliance_tools')
@token_required(scopes=CORP_REQUIRED_SCOPES)
def alliancetools_add_char(request, token):
    try:
        AllianceToolCharacter.objects.get_or_create(character=EveCharacter.objects.get(character_id=token.character_id))
        return redirect('alliancetools:dashboard')

    except:
        messages.error(request, ('Error Adding Character!'))

    return redirect('alliancetools:dashboard')


@login_required
def structures(request):
    if request.user.has_perm('alliancetools.access_alliance_tools_structures'):
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').all().prefetch_related('structureservice_set')
    elif request.user.has_perm('alliancetools.access_alliance_tools_structures_renter'):
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').filter(corporation__corporation_id=settings.RENTER_HOLDING_CORP_ID).prefetch_related('structureservice_set')
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    context = {
        'structures': structures,
        'add_tokens' : request.user.has_perm('alliancetools.admin_alliance_tools'),
        'view_fittings' : (request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings') or request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings_renter'))
    }
    return render(request, 'alliancetools/structures.html', context=context)


@login_required
def structure(request, structure_id=None):
    if request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings'):
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').all().prefetch_related('structureservice_set')
    elif request.user.has_perm('alliancetools.access_alliance_tools_structure_fittings_renter'):
        structures = Structure.objects.select_related('corporation', 'system_name', 'type_name').filter(corporation__corporation_id=settings.RENTER_HOLDING_CORP_ID).prefetch_related('structureservice_set')
    else:
        raise PermissionDenied('You do not have permission to be here. This has been Logged!')

    structure = Structure.objects.get(structure_id=structure_id)

    if structure not in structures:
        raise PermissionDenied('You do not have permission to view the selected station.  This has been Logged!')

    fittings = CorpAsset.objects.filter(location_id=structure_id)
    fit_ob = {'Cargo':[], 'FighterBay':[], 'StructureFuel':[]}

    fortizars = [35833,47516,47512, 47513, 47514, 47515]
    slot_layout ={'high':0,'med':0,'low':0,'rig':0,'service':1}   #  h m l r s
    if structure.type_id in fortizars:
        slot_layout = {'high':6,'med':5,'low':4,'rig':3,'service':5}
    elif structure.type_id == 35832:  # astra
        slot_layout = {'high':4,'med':4,'low':3,'rig':3,'service':3}
    elif structure.type_id == 35834:  # keep
        slot_layout = {'high':8,'med':6,'low':5,'rig':3,'service':7}
    elif structure.type_id == 35827:  # soyito
        slot_layout = {'high':6,'med':4,'low':3,'rig':3,'service':6}
    elif structure.type_id == 35826:  # azbel
        slot_layout = {'high':4,'med':3,'low':2,'rig':3,'service':5}
    elif structure.type_id == 35825:  # riat
        slot_layout = {'high':3,'med':2,'low':1,'rig':3,'service':3}
    elif structure.type_id == 35835:  # ath
        slot_layout = {'high':3,'med':3,'low':1,'rig':3,'service':3}
    elif structure.type_id == 35836:  # tat
        slot_layout = {'high':5,'med':4,'low':3,'rig':3,'service':5}

    # fort, astra, keep
    # 35833 "Fortizar", 47516 "'Prometheus' Fortizar", 47512 "'Moreau' Fortizar", 47513 "'Draccous' Fortizar", 47514 "'Horizon' Fortizar", 47515 "'Marginis' Fortizar" 6 5 4 3 5
    # 35832 "Astrahus" 4 4 3 3 3, 35834 "Keepstar" 8 6 5 3 7

    # rait, azbel, sotiyo
    # 35825 "Raitaru"3 2 1 3 3 , 35826 "Azbel" 4 3 2 3 5, 35827 "Sotiyo" 6 4 3 3 6

    # athanor, tatara
    # 35835 "Athanor" 3 3 1 3 3, 35836 "Tatara" 5 4 3 3 5

    # cyno, gates, jammers
    # 0 0 0 0 1
    # 37534 "Tenebrex Cyno Jammer", 35840 "Pharolux Cyno Beacon", 35841 "Ansiblex Jump Gate"

    for fi in fittings:
        if fi.location_flag == 'Cargo':
            fit_ob['Cargo'].append(fi)
        elif fi.location_flag == 'FighterBay':
            fit_ob['FighterBay'].append(fi)
        elif fi.location_flag == 'StructureFuel':
            fit_ob['StructureFuel'].append(fi)
        else:
            fit_ob[fi.location_flag] = fi
    context = {
        'structure': structure,
        'slots': slot_layout,
        'fittings': fit_ob
    }
    return render(request, 'alliancetools/structure.html', context=context)


@login_required
def add_job(request):
    if request.method == 'POST':
        form = AddJob(request.POST)

        # check whether it's valid:
        if form.is_valid():
            AllianceToolJob.objects.create(creator=request.user.profile.main_character,
                                            title=form.cleaned_data['title'],
                                            description=form.cleaned_data['description'],
                                            created=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))
            messages.info(request, "Job Added")
            return redirect('alliancetools:jobs_board')
    else:
        form = AddJob()
        return render(request, 'alliancetools/add_job.html', {'form': form})


@login_required
def add_comment(request, job_id=None):
    if request.method == 'POST':
        form = AddComment(request.POST)

        # check whether it's valid:
        if form.is_valid():
            AllianceToolJobComment.objects.create(commenter=request.user.profile.main_character,
                                           job=AllianceToolJob.objects.get(id=request.POST.get('job_id')),
                                           comment=form.cleaned_data['comment'],
                                           created=datetime.datetime.utcnow().replace(tzinfo=timezone.utc))
            messages.info(request, "Comment Added")
            return redirect('alliancetools:jobs_board')
    else:
        form = AddComment()
        task = AllianceToolJob.objects.get(pk=job_id)
        return render(request, 'alliancetools/add_comment.html', {'form': form, 'job': task})


@login_required
def edit_job(request, job_id=None):
    if request.method == 'POST':
        form = EditJob(request.POST)

        # check whether it's valid:
        if form.is_valid():
            jb = AllianceToolJob.objects.get(id=request.POST.get('job_id'))
            jb.title = form.cleaned_data['title']
            jb.description = form.cleaned_data['description']
            jb.save()
            messages.info(request, "Edit Successful")
            return redirect('alliancetools:jobs_board')
    else:
        task = AllianceToolJob.objects.get(pk=job_id)
        form = EditJob(initial={'title': task.title,
                                'description': task.description})
        return render(request, 'alliancetools/edit_job.html', {'form': form, 'job': task})


@login_required
def mark_complete(request, job_id=None):
    AllianceToolJob.objects.filter(id=job_id).update(
        completed=datetime.datetime.utcnow().replace(tzinfo=timezone.utc),
        assined_to=request.user.profile.main_character)
    messages.info(request, "Job Closed")
    return redirect('alliancetools:jobs_board')


@login_required
def audit_log(request, job_id=None):
    crud_list = CRUDEvent.objects.filter(object_id=job_id)
    cruds = []
    for event in crud_list:
        json_array = json.loads(event.object_json_repr)

        cruds.append({'user': UserProfile.objects.get(user=event.user).main_character,
                     'datetime': event.datetime,
                     'title': json_array[0]['fields']['title'],
                     'description': json_array[0]['fields']['description']})
    return render(request, 'alliancetools/audit_log.html', {'cruds': cruds})


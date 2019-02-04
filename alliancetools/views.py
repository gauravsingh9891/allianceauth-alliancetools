import logging

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib import messages
from esi.decorators import token_required
from allianceauth.eveonline.models import EveCharacter
from django.db import IntegrityError

from .models import AllianceToolCharacter

CORP_REQUIRED_SCOPES = ['esi-characters.read_notifications.v1',
                        'esi-assets.read_corporation_assets.v1',
                        'esi-characters.read_corporation_roles.v1',
                        'esi-wallet.read_corporation_wallets.v1',
                        'esi-corporations.read_structures.v1',
                        'esi-universe.read_structures.v1']


@login_required
def dashboard(request):
    main_char = request.user.profile.main_character

    try:
        main_character = AllianceToolCharacter.objects.get(character=main_char)
        alt_list = [co.character for co in main_char.character_ownership.user.character_ownerships.all()]
        alts = []
        for alt in alt_list:
            if not main_char == alt:
                try:
                    alts.append(AllianceToolCharacter.objects.get(character=alt))
                except:
                    alt_item = {}
                    alt_item['character'] = alt
                    alts.append(alt_item)

        context = {
            'main_character': main_character,
            'alts': alts,
        }
        return render(request, 'alliancetools/dashboard.html', context=context)

    except:
        logging.exception("message")

    return render(request, 'alliancetools/dashboard.html')


@login_required
@token_required(scopes=CORP_REQUIRED_SCOPES)
def alliancetools_add_char(request, token):
    try:
        AllianceToolCharacter.objects.get_or_create(character=EveCharacter.objects.get(character_id=token.character_id))
        return redirect('alliancetools:dashboard')

    except:
        messages.error(request, ('Error Adding Character!'))

    return redirect('alliancetools:dashboard')

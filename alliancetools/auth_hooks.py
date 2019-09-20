from . import urls
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook
from allianceauth.authentication.models import UserProfile, State


class AllianceMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Alliance Toolbox',
                              'fa fa-empire fa-fw',
                              'alliancetools:dashboard',
                              navactive=['alliancetools:dashboard'])

    def render(self, request):
        if request.user.has_perm('alliancetools.admin_alliance_tools') or request.user.has_perm('alliancetools.corp_level_alliance_tools'):
            return MenuItemHook.render(self, request)
        return ''


class StructureMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Structures',
                              'fa fa-building fa-fw',
                              'alliancetools:structures',
                              navactive=['alliancetools:structures'])

    def render(self, request):
        if request.user.has_perm('alliancetools.access_alliance_tools_structures') or request.user.has_perm('alliancetools.access_alliance_tools_structures_renter') or request.user.has_perm('alliancetools.corp_level_alliance_tools'):
            return MenuItemHook.render(self, request)
        return ''


class TimerMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Internal Timers',
                              'fa fa-clock-o fa-fw',
                              'alliancetools:timers',
                              navactive=['alliancetools:timers'])

    def render(self, request):
        member_state = State.objects.get(name='Member')
        if request.user.profile.state == member_state:
            return MenuItemHook.render(self, request)
        return ''

class MoonTimerMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Moon Extractions',
                              'fa fa-moon-o fa-fw',
                              'alliancetools:moons',
                              navactive=['alliancetools:moons'])

    def render(self, request):
        if request.user.has_perm('alliancetools.view_moonextractevent'):
            return MenuItemHook.render(self, request)
        return ''



class PocoMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Customs Offices',
                              'fa fa-globe fa-fw',
                              'alliancetools:pocos',
                              navactive=['alliancetools:pocos'])

    def render(self, request):
        if request.user.has_perm('alliancetools.admin_alliance_tools') or request.user.has_perm('alliancetools.access_alliance_tools_structures_renter'):
            return MenuItemHook.render(self, request)
        return ''


class TxfrMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Structure Txfrs',
                              'fa fa-exchange fa-fw',
                              'alliancetools:txfr',
                              navactive=['alliancetools:txfr'])

    def render(self, request):
        if request.user.has_perm('alliancetools.admin_alliance_tools') or request.user.has_perm('alliancetools.access_alliance_tools_structures_renter'):
            return MenuItemHook.render(self, request)
        return ''


class JobsMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Job Board',
                              'fa fa-tasks fa-fw',
                              'alliancetools:jobs_board',
                              navactive=['alliancetools:jobs_board'])

    def render(self, request):
        if request.user.has_perm('alliancetools.add_alliancetooljobcomment'):
            return MenuItemHook.render(self, request)
        return ''


class ContactsMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Alliance Contacts',
                              'fa fa-address-card fa-fw',
                              'alliancetools:contacts',
                              navactive=['alliancetools:contacts'])

    def render(self, request):
        if request.user.has_perm('alliancetools.admin_alliance_tools'):
            return MenuItemHook.render(self, request)
        return ''

@hooks.register('menu_item_hook')
def register_menu():
    return AllianceMenu()

@hooks.register('menu_item_hook')
def register_menu():
    return ContactsMenu()

@hooks.register('menu_item_hook')
def register_menu():
    return StructureMenu()

@hooks.register('menu_item_hook')
def register_menu():
    return TimerMenu()

@hooks.register('menu_item_hook')
def register_menu():
    return MoonTimerMenu()

@hooks.register('menu_item_hook')
def register_menu():
    return TxfrMenu()

@hooks.register('menu_item_hook')
def register_menu():
    return PocoMenu()

@hooks.register('menu_item_hook')
def register_menu():
    return JobsMenu()


@hooks.register('url_hook')
def register_url():
    return UrlHook(urls, 'alliancetools', r'^alliancetools/')


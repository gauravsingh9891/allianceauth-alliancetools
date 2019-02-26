from . import urls
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook


class AllianceMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Alliance Toolbox',
                              'fa fa-empire fa-fw',
                              'alliancetools:dashboard',
                              navactive=['alliancetools:dashboard'])

    def render(self, request):
        if request.user.has_perm('alliancetools.admin_alliance_tools'):
            return MenuItemHook.render(self, request)
        return ''


class StructureMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(self, 'Structures',
                              'fa fa-building fa-fw',
                              'alliancetools:structures',
                              navactive=['alliancetools:structures'])

    def render(self, request):
        if request.user.has_perm('alliancetools.access_alliance_tools_structures'):
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


@hooks.register('menu_item_hook')
def register_menu():
    return AllianceMenu()


@hooks.register('menu_item_hook')
def register_menu():
    return StructureMenu()


@hooks.register('menu_item_hook')
def register_menu():
    return JobsMenu()


@hooks.register('url_hook')
def register_url():
    return UrlHook(urls, 'alliancetools', r'^alliancetools/')


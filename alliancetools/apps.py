from django.apps import AppConfig

class AllianceToolsConfig(AppConfig):
    name = 'alliancetools'
    label = 'alliancetools'

    def ready(self):
        import alliancetools.signals

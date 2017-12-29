from happypanda.common import (hlogger, exceptions, utils, constants, exceptions, config)
from happypanda.core.command import Command, CommandEvent, AsyncCommand
from happypanda.interface import enums
from happypanda.core import updater, message

log = hlogger.Logger(__name__)

class CheckUpdate(Command):
    """
    Check for new release
    """

    def __init__(self, priority = constants.Priority.Low):
        super().__init__(priority)

    def main(self, silent=True, force=False, push=False) -> dict:
        if force or config.check_release_interval.value:
            u = updater.check_release(silent=silent)
            if u and push:
                msg = message.Notification(
                    "Changelog coming soon! For now, please visit the github repo to see the new changes",
                    "HappyPanda X {} is available!".format(u['tag']))
                msg.add_action(1, "Update & Restart", "button")
                msg.add_action(2, "Skip", "button")
                client_answer = self.push(msg).get(msg.id, timeout=20)
                if client_answer and 1 in client_answer:
                    UpdateApplication().run(restart=True, silent=silent)
            return u

class UpdateApplication(Command):
    """
    Check for new release and update the application
    """

    update = CommandEvent("update", bool, bool)

    def __init__(self, priority = constants.Priority.Low):
        super().__init__(priority)

    def main(self, download_url=None, restart=True, silent=True) -> bool:
        st = False
        if download_url:
            rel = download_url
        else:
            rel = updater.check_release(silent=silent)
            if rel:
                rel = rel['url']
        if rel:
            new_rel = updater.get_release(rel, silent=silent)
            if new_rel:
                st = updater.register_release(new_rel['path'], silent, restart=restart)
        self.update.emit(st, restart)
        return st

class RestartApplication(Command):
    """
    Restart the appplication
    """

    restart = CommandEvent("restart")

    def __init__(self, priority = constants.Priority.Normal):
        super().__init__(priority)

    def main(self):
        self.restart.emit()

class ShutdownApplication(Command):
    """
    Shutdown the appplication
    """

    shutdown = CommandEvent("shutdown")

    def __init__(self, priority = constants.Priority.Normal):
        super().__init__(priority)

    def main(self):
        self.shutdown.emit()
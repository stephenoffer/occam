"""Errors the appointment service raises. The CLI turns them into exit code 2."""


class AppointmentError(Exception):
    """Base class: something the user asked for can't be done."""


class NotFound(AppointmentError):
    pass


class InvalidMove(AppointmentError):
    """The appointment's current status doesn't allow this."""


class SlotUnavailable(AppointmentError):
    """The clinician isn't working then, or the time is already taken."""


class TooEarly(AppointmentError):
    """Marking arrival or a no-show before the appointment has started."""


class TooLate(AppointmentError):
    """Cancelling or confirming an appointment that has already started."""

class TripError(Exception):
    """An error whose message is safe to show the user and carries the HTTP status to return."""

    status_code = 502

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UpstreamUnavailable(TripError):
    status_code = 503


class UpstreamAuth(TripError):
    status_code = 503


class UpstreamBadResponse(TripError):
    status_code = 502


class NoRouteFound(TripError):
    status_code = 422


class DepartureRejected(TripError):
    status_code = 422


class InvalidTrip(TripError):
    status_code = 400

from rest_framework.negotiation import BaseContentNegotiation


class IgnoreNegotiation(BaseContentNegotiation):
    """Lets a CSV export return a plain HttpResponse whatever Accept header the client sends."""

    def select_parser(self, request, parsers):
        return parsers[0]

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type

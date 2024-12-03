from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User

class AutoLoginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # Create a default admin user if it doesn't exist
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin')

    def __call__(self, request):
        if not request.user.is_authenticated:
            # Auto-login with admin user
            user = authenticate(username='admin', password='admin')
            login(request, user)
        return self.get_response(request)
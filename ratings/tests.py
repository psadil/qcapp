from django.http import HttpResponse


# Create your tests here.
def index(request):
    return HttpResponse("Hello, world. You're at the polls index.")

import time
import traceback
from datetime import date, datetime, timedelta
from calendar import Calendar, HTMLCalendar

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseForbidden, Http404, HttpRequest
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from nadine.models.core import UserProfile, Membership
from nadine.models.usage import CoworkingDay, Event
from nadine.models.resource import Room

from members.forms import EventForm
from members.views.core import is_active_member


@login_required
@user_passes_test(is_active_member, login_url='member_not_active')
def events_google(request, location_slug=None):
    return render(request, 'members/events_google.html', {'settings': settings})


def coerce_times(start, end, date):
    if len(start) > 5:
        start = start.split(" ")
        if start[1] == 'PM':
            mil_start = start[0].split(":")
            if int(mil_start[0]) < 12:
                hour = int(mil_start[0]) + 12
            else:
                hour = mil_start[0]
            start = str(hour) + ':' + mil_start[1]
        else:
            start = start[0]
    if len(end) > 5:
        end = end.split(" ")
        if end[1] == 'PM':
            mil_end = end[0].split(":")
            if int(mil_end[0]) < 12:
                hour = int(mil_end[0]) + 12
            else :
                hour = mil_end[0]
            end = str(hour) + ':' + mil_end[1]
        else:
            end = end[0]

    start_dt = datetime.strptime(date + " " + start, "%Y-%m-%d %H:%M")
    start_ts = timezone.make_aware(start_dt, timezone.get_current_timezone())
    end_dt = datetime.strptime(date + " " + end, "%Y-%m-%d %H:%M")
    end_ts = timezone.make_aware(end_dt, timezone.get_current_timezone())

    return start_ts, end_ts, start, end

@login_required
@user_passes_test(is_active_member, login_url='member_not_active')
def create_booking(request):
    # Process URL variables
    has_av = request.GET.get('has_av', None)
    has_phone = request.GET.get('has_phone', None)
    floor = request.GET.get('floor', None)
    seats = request.GET.get('seats', None)
    date = request.GET.get('date', str(timezone.now().date()))
    start = request.GET.get('start', str(datetime.now().hour) + ':' + str(datetime.now().minute))
    end = request.GET.get('end', str(datetime.now().hour + 2) + ':' + str(datetime.now().minute))

    # Turn our date, start, and end strings into timestamps
    start_ts, end_ts, start, end = coerce_times(start, end, date)


    #Make auto date for start and end if not otherwise given
    room_dict = {}
    rooms = Room.objects.available(start=start_ts, end=end_ts, has_av=has_av, has_phone=has_phone, floor=floor, seats=seats)

    # Get all the events for each room in that day
    target_date = start_ts.date()

    for room in rooms:
        calendar = room.get_calendar(target_date)
        room_dict[room] = calendar

        # Infuse calendar with search range
        search_start = start.replace(':', '')
        search_end = end.replace(':', '')

        for block in calendar:
            id = block['mil_hour'] + block['minutes']
            if int(search_start) <= int(id) and int(id) <= int(search_end):
                block['searched'] = True

    if request.method == 'POST':
        room = request.POST.get('room')
        start = request.POST.get('start')
        end = request.POST.get('end')
        date = request.POST.get('date')

        return HttpResponseRedirect(reverse('member_confirm_booking', kwargs={'room': room, 'start': start, 'end': end, 'date': date}))

    context = {'rooms': rooms, 'start':start, 'end':end, 'date': date,
        'has_av':has_av, 'floor': floor, 'has_phone': has_phone,
        'room_dict': room_dict}
    return render(request, 'members/booking_create.html', context)

@login_required
@user_passes_test(is_active_member, login_url='member_not_active')
def confirm_booking(request, room, start, end, date):
    user = request.user
    room = get_object_or_404(Room, name=room)
    page_message = None

    start_ts, end_ts, start, end = coerce_times(start, end, date)

    target_date = start_ts.date()

    event_dict = {}
    calendar = room.get_calendar(target_date)
    event_dict[room] = calendar

    # Infuse room calendar with search range
    search_start = start.replace(':', '')
    search_end = end.replace(':', '')

    for block in calendar:
        block_int = int(block['mil_hour'] + block['minutes'])
        if int(search_start) <= block_int and block_int <= int(search_end):
            block['searched'] = True

    if request.method == 'POST':
        user = request.user
        room = request.POST.get('room')
        room = get_object_or_404(Room, name=room)
        start = request.POST.get('start')
        end = request.POST.get('end')
        date = request.POST.get('date')
        start_ts, end_ts = coerce_times(start, end, date)
        description = request.POST.get('description', '')
        charge = request.POST.get('charge', 0)
        is_public = request.POST.get('is_public', False)
        event = Event(user=user, room=room, start_ts=start_ts, end_ts=end_ts, description=description, charge=charge, is_public=is_public)

        stillAv = Room.objects.available(start=start_ts, end=end_ts)

        if room in stillAv:
            try:
                event.save()

                return HttpResponseRedirect(reverse('member_profile', kwargs={'username': user.username}))

            except Exception as e:
                page_message = str(e)
                logger.error(str(e))
        else:
            page_message = 'This room is no longer available at the requested time.'
    else:
        booking_form = EventForm()

    context = {'booking_form':booking_form, 'start':start, 'end':end,
        'room': room, 'date': date, 'page_message': page_message,
        'event_dict': event_dict}
    return render(request, 'members/booking_confirm.html', context)

@login_required
@user_passes_test(is_active_member, login_url='member_not_active')
def calendar(request):
    page_message = None
    events = Event.objects.filter(is_public=True)
    data = []

    for event in events:
        host = get_object_or_404(User, id=event.user_id)
        data.append((event, host))

    if request.method == 'POST':
        user = request.user
        start = request.POST.get('start')
        end = request.POST.get('end')
        date = request.POST.get('date')

        start_ts, end_ts = coerce_times(start, end, date)

        if start_ts < end_ts :

            description = request.POST.get('description', '')
            charge = request.POST.get('charge', 0)
            is_public = True

            event = Event(user=user, start_ts=start_ts, end_ts=end_ts, description=description, charge=charge, is_public=is_public)

            event.save()

            return HttpResponseRedirect(reverse('member_calendar'))
        else:
            page_message = "Did not save your event. Double check that the event start is before the end time. Thank you."

    context = {'data': data, 'GOOGLE_CALENDAR_ID': settings.GOOGLE_CALENDAR_ID,
        'GOOGLE_API_KEY': settings.GOOGLE_API_KEY, 'page_message': page_message}
    return render(request, 'members/calendar.html', context)


# Copyright 2016 Office Nomads LLC (http://www.officenomads.com/) Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0 Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.

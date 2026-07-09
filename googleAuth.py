#!/usr/bin/env python3

from __future__ import annotations

import logging
import os
import socket
import traceback
from gettext import gettext as _
from typing import cast, no_type_check

import httplib2
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from oauthlib.oauth2.rfc6749.errors import AccessDeniedError

from BTSpeak import authTools, dialogs, terminal, web_search
from BTSpeak.terminal import TARGET_TERMINAL

log = logging.getLogger(__name__)

successMessage = _("Login succeeded.") + " " + _("Please return to Blazie mode.")
desktopLoadingMessage = _("Desktop mode browser will now load for Google login.") + " " + _("Press Enter and wait a few moments.")
noNetworkMessage = _("Google Service not available.") + " " + _("Check Wi-Fi connection.")
googleLoginSuccessMessage = _("Login successful.") + " " + _("Returning to the application.")
noServiceMessage = _("Google service not available.")


def loadGoogleService(apiName: str, scopes: list[str], serviceTuple: tuple[str, str]) -> object | None:
    log.info(f"{apiName=}")
    service = None
    clientFile = authTools.getClientFile(apiName)
    tokenFile = authTools.makeTokenPath(apiName, key_name="userTokens")

    if clientFile is None:
        dialogs.show_message(noServiceMessage)
        return None

    try:
        service = callService(clientFile, scopes, tokenFile, serviceTuple)

        if service is None or not checkService(apiName, service):
            runGoogleAuth(clientFile, tokenFile, scopes)
            service = callService(clientFile, scopes, tokenFile, serviceTuple)

            if not checkService(apiName, service):
                return None

    except HttpError:
        terminal.switch(TARGET_TERMINAL)
        dialogs.show_message(noServiceMessage)
        log.error(traceback.format_exc())

    except (httplib2.ServerNotFoundError, socket.gaierror, OSError, TransportError):
        terminal.switch(TARGET_TERMINAL)
        dialogs.show_message(noNetworkMessage)

    except Exception as e:
        terminal.switch(TARGET_TERMINAL)
        raise e

    return service


def callService(clientFile: str, scopes: list[str], tokenFile: str, serviceTuple: tuple[str, str]) -> object | None:
    creds: Credentials | None = None

    if os.path.exists(tokenFile):
        creds = Credentials.from_authorized_user_file(tokenFile, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                saveUserTokens(tokenFile, creds)
            except (httplib2.ServerNotFoundError, TransportError):
                raise
            except Warning:
                # stale token with mismatched scopes - delete it so re-auth is triggered
                os.remove(tokenFile)
                return None
            except Exception:
                return None
        else:
            return None

    API, version = serviceTuple
    try:
        service = build(API, version, credentials=creds)
        return cast(object, service)
    except (httplib2.ServerNotFoundError, socket.gaierror, TransportError):
        raise


def saveUserTokens(tokenFile: str, creds: Credentials) -> None:
    with open(tokenFile, 'w') as token:
        token.write(creds.to_json())
    return


@no_type_check
def checkService(apiName: str, service: object) -> bool:
    try:
        match apiName:
            case 'googleDrive':
                service.files().list(pageSize=1).execute()
            case 'googleCalendar':
                service.calendarList().list(maxResults=1).execute()
            case 'googleContacts':
                service.people().connections().list(resourceName='people/me', pageSize=1, personFields='names').execute()
            case 'youtube':
                service.channels().list(part="snippet", mine=True).execute()
        return True
    except Exception:
        return False


def runGoogleAuth(clientFile: str, tokenFile: str, scopes: list[str]) -> Credentials | None:
    log.info(f"{clientFile=} {tokenFile=}")
    # the next two lines are necessary to shutdown runActivity() so its messaging/activity doesn't run into the login sequence
    dialogs.stopActivityIndicator()
    dialogs.clearScreen()

    if not authTools.testNetwork():
        log.warning("no network")
        return None

    dialogs.show_message(desktopLoadingMessage)
    terminal.switch_and_wait(terminal.TARGET_DESKTOP)

    # here we can't use flow to open the browser because if doesn't do very good error checking
    # and chromium can leave stale lock files behinbd, blocking launch silently.
    # web_search.open_url detects these errors and deletes the lock files automatically
    OAUTH_PORT = 8085
    flow = InstalledAppFlow.from_client_secrets_file(clientFile, scopes)
    flow.redirect_uri = f"http://localhost:{OAUTH_PORT}/"
    auth_url, state = flow.authorization_url()
    web_search.open_url(auth_url)
    try:
        creds = flow.run_local_server(port=OAUTH_PORT, open_browser=False, success_message=successMessage, state=state)
    except AccessDeniedError:
        dialogs.show_message(_("Access denied: Google login was canceled or denied."))
        return None

    if creds:
        saveUserTokens(tokenFile, creds)
        terminal.switch(TARGET_TERMINAL)
        dialogs.show_message(googleLoginSuccessMessage)
        return creds
    else:
        return None

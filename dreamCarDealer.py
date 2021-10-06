
#TODO: dodatni iskalni parametri in branje le-teh iz JSON-a

# importi
from email.mime import text
import json
from requests import Session
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from re import search
from datetime import datetime, timedelta
from smtplib import SMTP_SSL, SMTPException
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from json import load, dump
from os.path import dirname, realpath, join, isfile
from time import sleep

# globalne konstante
from GLOBALS.URLsAndQueryParams import BASE_URL, ADS_SUB_SITE, URL_PARAMS
from GLOBALS.extraCarQueryParameters import suitableParameters
from GLOBALS.terminalColors import termColors
from secrets import MAIL_ACCOUNT_NAME, MAIL_ACCOUNT_PASSWORD, MAIL_SEND_TO

SAVED_DATA_PATH = join(realpath(dirname(__file__)), "STORAGE", "savedData.txt")
DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"
SLEEP_TIME_BETWEEN_ADS = 0.075 # [s] premor med pridobivanjem oglasov, da spletna stran ne dobi "robotoziranega obcutka"

# časovni razpon, ki me zanima za oglase
lastDate = datetime.now() - timedelta(days=2)
# ID zadnjega oglasa
lastAdID = -1
# seja za HTTP zahtevke
session = Session()
session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# funkcija, preberi podatke o zadnjem datumu in ID oglasu (ce obstaja)
def readSavedDataFromJSON():
    # global, da jih lahko assignas v funkciji
    global lastDate
    global lastAdID

    if isfile(SAVED_DATA_PATH):
        with open(SAVED_DATA_PATH, "r") as f:
            dataJSON = json.load(f)
            lastDate = datetime.strptime(dataJSON["date"], DATETIME_FORMAT)
            lastAdID = dataJSON["id"]

# funkcija, preberi podatke o zadnjem datumu in ID oglasu
def writeSavedDataFromJSON():
    with open(SAVED_DATA_PATH, "w") as f:
            dataJSON = {
                "date": lastDate.strftime(DATETIME_FORMAT),
                "id": lastAdID
            }
            dump(dataJSON, f)

# funkcija pošlje mail z rezultati
def sendMail(msg, subject="Avto oglasi"):
    port = 465

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = MAIL_ACCOUNT_NAME
    message["To"] = MAIL_SEND_TO
    text = MIMEText(msg, "plain")
    message.attach(text)

    try:
            server = SMTP_SSL("smtp.gmail.com", port)
            server.login(MAIL_ACCOUNT_NAME, MAIL_ACCOUNT_PASSWORD)
            server.sendmail(MAIL_ACCOUNT_NAME, MAIL_SEND_TO, message.as_string())
            server.quit()

    except SMTPException as e:
        print(e)
        print(f"{termColors.WARNING }{e}\n{termColors.ENDC}")
        quit()

# funkcija (wrapper) pošlje napake na mail
def sendErrorNotification(errorMessage):
    sendMail(errorMessage, subject="Napaka v skripti za avtoNet")
    print(f"{termColors.WARNING }{errorMessage}\n{termColors.ENDC}")
    quit()

# funkcija ki vrne true/false, če je prava znamka avta
def isCarManufacturerSuitable(_string):
    try:
        carBrand = _string.split(' ')[0]
        if carBrand in suitableParameters.carBrands:
            return True
        else: 
            return False

    except Exception as e:
        sendErrorNotification("Napaka v funkciji isCarManufacturerSuitable...\n" + e)

# funkcija vrne true/false, če ustreza kriterijem za gorivo
def isFuelTypeSuitable(table):
    try:
        listRows = table.find_all("tr") # pridobim vse <tr> v katerih so podatki
        for row in listRows:
            header = row.th # <th> -> naslov vrste
            data = row.td # <td> -> data vrste
            if header == None or data == None: # verjetno prazna naslovna vrstica (continue)
                continue

            if "Gorivo:" in header.text: # vrstica z gorivom
                for el in suitableParameters.fuelTypes:
                    if el in data.text: # kriterij ("in" uporabim za substring, ker še neke space nameče)
                        return True

                return False

    except Exception as e:
        sendErrorNotification("Napaka v funkciji isFuelTypeSuitable...\n" + e)

# funkcija pridobi HTML strani in ga preparsa (opcijski query parametri)
def getSoupObjectFromURL(_urlSubSite="", _params=None):
    url = BASE_URL + _urlSubSite
    res = session.get(url, params=_params)
    print("Pridobljen zahtevek z URL:\n" + res.url + "\n")

    soupObj = BeautifulSoup(res.content, "html5lib")
    return soupObj

# funkcija ki obdela vse oglase v adList
def processAds(adList, myAdsStr):
    for ad in adList:
        if ad.find("div", class_="GO-Results-Top-Photo") != None: # če najde ta div je iz topAd-a (in to me ne zanima, tak da preskoči)
            continue
        
        # pridobi HTML strani za avto
        a_tag = ad.a
        subUrl = a_tag["href"][2:]
        htmlAd = getSoupObjectFromURL(_urlSubSite=subUrl)
        sleep(SLEEP_TIME_BETWEEN_ADS)

        # pridobi datum oglasa
        divDate = htmlAd.find("div", class_="col-12 col-lg-6 p-0 pl-1 text-center text-lg-left")
        dateString = divDate.text # vzemi text iz html elementa
        regex = search(r"\d", dateString) # poišči prvi digit z regex
        dateString_digitsExtract = dateString[regex.start() : ]
        regex = search(r"\n", dateString_digitsExtract) # poišči konec digitov (tam je zank "\n")
        dateString_digitsOnly = dateString_digitsExtract[0 : regex.start()]
        siteDate = datetime.strptime(dateString_digitsOnly, "%d.%m.%Y %H:%M:%S")
        
        # ustreznosti kriterijem
        if siteDate < lastDate: # preveri če datum ni prestar (če je se konča iskanje oglasov in returna iz funkcije)
            return False, myAdsStr # vrne false, ker tukaj pride ne pride do konca oglasov, a so datumi že prestari

        if not isCarManufacturerSuitable(htmlAd.title.text): # pogoj proizvajalca
            continue

        if not isFuelTypeSuitable(htmlAd.find_all("table")[0]): # pogoj tipa motorja (* prvi <table> tag je tabela, ki jo rabim)
            continue
        
         # dodaj link oglasa v string (ustreza vsem kriterijem)
        myAdsStr += (htmlAd.title.text + "\n" + BASE_URL + subUrl + "\n\n")

    return True, myAdsStr # vrne true, vsi oglasi so datumsko ustrezni(tako da se iskanje nadaljuje)

# funkcija ki naredi in pridobi poizvedbo nad oglasi
def searchForAds():
    currTime = datetime.now()
    acceptableAdsStr = ""

    pageList = []
    currentPageNumber = 1
    maxPageNumber = 99
    allAdsInDateSpan = True

    while currentPageNumber <= maxPageNumber and allAdsInDateSpan:
        # pridobi parsan html
        soupObj = getSoupObjectFromURL(_urlSubSite=ADS_SUB_SITE, _params=URL_PARAMS) # avto net s custom parametri

        # div container z oglasi
        adsContainer = soupObj.find("div", class_= "col-12 col-lg-9") # container div za vse ad-e

        # prestej stevilo strani
        if currentPageNumber == 1:
            page = soupObj.find_all("ul", id= "GO-naviprevnext")[1] # za več strani
            if page != None:
                pageList = page.find_all("li", class_= "page-item") # vse strani
                maxPageNumber = len(pageList) - 3 # vse strani - naprej/nazaj elementa

        # seznam oglasov
        if adsContainer != None:
            adList = adsContainer.find_all("div", class_= "GO-Results-Row")

            # procesiranje oglasov
            allAdsInDateSpan, acceptableAdsStr = processAds(adList, acceptableAdsStr)

        # naslednja stran
        currentPageNumber += 1
        URL_PARAMS["stran"] += currentPageNumber

    # shrani cas
    global lastDate # global, da se vrednost shrani v globalno spremenljivko in ne lokalno
    lastDate = currTime

    if acceptableAdsStr == "":
        # ni zadetkov
        print("Ni novih oglasov...")

    else:
        # pošlji izbrane oglasi na mail
        sendMail("Ugodni avtomobilski oglasi za datum " + currTime.strftime(DATETIME_FORMAT) + "\n\n" + acceptableAdsStr) 
        print(acceptableAdsStr)


if __name__ == "__main__":
    print("\n")

    # preberi zadnji datum in id iz file-a
    readSavedDataFromJSON()
    # zacni "algoritem iskanja in procesiranja oglasov" in poslji mail
    searchForAds()
    # zapisi zadnji datum in id v file
    writeSavedDataFromJSON()

    print(f"{termColors.OKCYAN }Program se je zaključil\n{termColors.ENDC}")
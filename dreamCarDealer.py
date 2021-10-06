
#TODO: dodatni iskalni parametri in branje le-teh iz JSON-a

# importi
from email.mime import text
import json
from requests import Session
from urllib.parse import urlencode, urlparse, parse_qs
from bs4 import BeautifulSoup
from re import search
from datetime import datetime, timedelta
from smtplib import SMTP_SSL, SMTPException
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from json import load, dump
from os.path import dirname, realpath, join, isfile
from time import time, sleep
from msvcrt import kbhit, getch

# globalne konstante
from GLOBALS.URLsAndQueryParams import BASE_URL, ADS_SUB_SITE, URL_PARAMS
from GLOBALS.extraCarQueryParameters import suitableParameters
from GLOBALS.terminalColors import termColors
from secrets import MAIL_ACCOUNT_NAME, MAIL_ACCOUNT_PASSWORD, MAIL_SEND_TO

STORAGE_FOLDER_PATH = join(realpath(dirname(__file__)), "STORAGE")
SAVED_DATA_PATH = join(STORAGE_FOLDER_PATH, "savedDataConfig.txt")
DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"
SLEEP_TIME_BETWEEN_ADS = 0.075 # [s] premor med pridobivanjem oglasov, da spletna stran ne dobi "robotoziranega obcutka"
TIME_WAIT_FOR_USER_INPUT = 7.0 # [s] cas, dokler programa caka na userjev input in blokira

# časovni razpon, ki me zanima za oglase
lastDate = datetime.now() - timedelta(days=14)
# ID zadnjega oglasa (prebrano iz fila)
lastAdID = -1
# ID trenutno najnovejsega oglasa
firstAdID = -1
# stevilka oglasa (po vrsti)
adNumber = 1
# seja za HTTP zahtevke
session = Session()
session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# funkcija, vrne true, ce je user v dolocenem casu kliknil tipko, false sicer
def waitAndReturnUserInput():
    startTime = endTime = time()
    print(f"{termColors.OKCYAN }Pritisni tipko za test mode (email se ne bo poslal, podatki iskanja ne bodo shranjeni)\n{termColors.ENDC}")

    while endTime - startTime < TIME_WAIT_FOR_USER_INPUT:
        if kbhit():
            print(f"{termColors.OKCYAN }Test mode aktiviran!\n{termColors.ENDC}")
            return True
        endTime = time()
        
    return False

# funkcija, preberi podatke o zadnjem datumu in ID oglasu (ce obstaja)
def readSavedDataFromJSON():
    # global, da se vrednost shrani v globalno spremenljivko in ne lokalno
    global lastDate
    global lastAdID

    if isfile(SAVED_DATA_PATH):
        with open(SAVED_DATA_PATH, "r") as f:
            dataJSON = json.load(f)
            lastDate = datetime.strptime(dataJSON["date"], DATETIME_FORMAT)
            lastAdID = dataJSON["id"]

# funkcija, preberi podatke o zadnjem datumu in ID oglasu
def writeSavedDataToJSON():
    with open(SAVED_DATA_PATH, "w") as f:
            dataJSON = {
                "date": lastDate.strftime(DATETIME_FORMAT),
                "id": firstAdID
            }
            dump(dataJSON, f)

def writeAdsToFile(data):
    fileName = str(lastDate.day) + "-" + str(lastDate.month) + "-" + str(lastDate.year) + "_" + str(lastDate.hour) + "-" + str(lastDate.minute) 
    filePath = join(STORAGE_FOLDER_PATH, fileName)

    with open(filePath, "w+") as f:
        f.write(data)

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
    # global, da se vrednost shrani v globalno spremenljivko in ne lokalno
    global firstAdID
    global adNumber

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
        parsedURL = urlparse(subUrl)
        adID = parse_qs(parsedURL.query)["id"][0]
        if lastAdID == adID: # preveri, ce je oglas s tem ID ze bil obdelan v prejsnjih zagonih programa
            return False, myAdsStr # vrne false

        if siteDate < lastDate: # preveri če datum ni prestar (če je se konča iskanje oglasov in returna iz funkcije)
            return False, myAdsStr # vrne false, ker tukaj pride ne pride do konca oglasov, a so datumi že prestari

        if not isCarManufacturerSuitable(htmlAd.title.text): # pogoj proizvajalca
            continue

        if not isFuelTypeSuitable(htmlAd.find_all("table")[0]): # pogoj tipa motorja (* prvi <table> tag je tabela, ki jo rabim)
            continue
        
        # shrani ID cisto prvega oglasa
        if firstAdID == -1:
            firstAdID = adID

         # dodaj link oglasa v string (ustreza vsem kriterijem)
        myAdsStr += (str(adNumber)+ ". " + htmlAd.title.text.split(":", 1)[0] + "\n" + BASE_URL + subUrl + "\n\n")

        # inkrementiraj stevilko oglasa
        adNumber += 1

    return True, myAdsStr # vrne true, vsi oglasi so datumsko ustrezni(tako da se iskanje nadaljuje)

# funkcija ki naredi in pridobi poizvedbo nad oglasi
def searchForAds():
    # global, da se vrednost shrani v globalno spremenljivko in ne lokalno
    global lastDate

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
                numOfPages = len(pageList) - 2 # stevilo strani je enako vsem "li" znackam minus 2 (za naprej/nazaj)
                maxPageNumber = min(numOfPages, 10) # omeji se na max 10 strani

        # seznam oglasov
        if adsContainer != None:
            adList = adsContainer.find_all("div", class_= "GO-Results-Row")

            # procesiranje oglasov
            allAdsInDateSpan, acceptableAdsStr = processAds(adList, acceptableAdsStr)

        # naslednja stran
        currentPageNumber += 1
        URL_PARAMS["stran"] += currentPageNumber

    # shrani cas 
    lastDate = currTime

    return acceptableAdsStr, currTime
    

if __name__ == "__main__":
    print("\n")

    # uporabnik lahko s pritiskom tipke aktivira testni nacin (email se ne poslje, podatki se ne shranijo)
    isTestModeActivated = waitAndReturnUserInput()

    # preberi zadnji datum in id iz file-a
    readSavedDataFromJSON()
    # zacni "algoritem iskanja in procesiranja oglasov" in poslji mail
    acceptableAdsStr, currTime = searchForAds()

    if acceptableAdsStr == "":
        # ni zadetkov
        print("Ni novih oglasov...")
    else:
        print(acceptableAdsStr)
        if not isTestModeActivated:
            # pošlji izbrane oglase na mail
            sendMail("Ugodni avtomobilski oglasi za datum " + currTime.strftime(DATETIME_FORMAT) + "\n\n" + acceptableAdsStr)
            # shrani oglase v file
            writeAdsToFile(acceptableAdsStr)

    # zapisi zadnji datum in id v file
    if not isTestModeActivated:
        writeSavedDataToJSON()

    print(f"{termColors.OKCYAN }Program se je zaključil\n{termColors.ENDC}")
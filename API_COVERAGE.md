# Copertura legacy 1:1

**91 operazioni su 88 percorsi: tutte registrate all’indirizzo originale.**

> La copertura prova metodo e percorso. La conformità comportamentale completa richiede il sorgente Flask reale e test golden-master.

## Access — 6 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| GET | `/Access/v1/classroom` | `/v3/upstream/Access/v1/classroom` | Basic legacy / Bearer migrazione |
| POST | `/Access/v1/classroom` | `/v3/upstream/Access/v1/classroom` | Basic legacy / Bearer migrazione |
| GET | `/Access/v1/covidStatement` | `/v3/upstream/Access/v1/covidStatement` | Basic legacy / Bearer migrazione |
| POST | `/Access/v1/covidStatement` | `/v3/upstream/Access/v1/covidStatement` | Basic legacy / Bearer migrazione |
| GET | `/Access/v1/covidStatementMessage` | `/v3/upstream/Access/v1/covidStatementMessage` | Pubblica |
| GET | `/Access/v1/getCSV` | `/v3/upstream/Access/v1/getCSV` | Basic legacy / Bearer migrazione |

## Badges — 20 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| GET | `/Badges/v1/QrCodeStatus/{tabletId}` | `/v3/upstream/Badges/v1/QrCodeStatus/{tabletId}` | Basic legacy / Bearer migrazione |
| GET | `/Badges/v1/QrCodeStatusAll` | `/v3/upstream/Badges/v1/QrCodeStatusAll` | Basic legacy / Bearer migrazione |
| GET | `/Badges/v1/ScanHistory` | `/v3/upstream/Badges/v1/ScanHistory` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v1/SyncMachine` | `/v3/upstream/Badges/v1/SyncMachine` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v1/checkQrCode` | `/v3/upstream/Badges/v1/checkQrCode` | Basic legacy / Bearer migrazione |
| GET | `/Badges/v1/generateQrCode` | `/v3/upstream/Badges/v1/generateQrCode` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v2/checkQrCode` | `/v3/upstream/Badges/v2/checkQrCode` | Basic legacy / Bearer migrazione |
| GET | `/Badges/v2/generateQrCode` | `/v3/upstream/Badges/v2/generateQrCode` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v2/generateQrCodeSPID` | `/v3/upstream/Badges/v2/generateQrCodeSPID` | Pubblica |
| POST | `/Badges/v2/getContactInfo` | `/v3/upstream/Badges/v2/getContactInfo` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v2/sendInfo` | `/v3/upstream/Badges/v2/sendInfo` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v2/sendRequestInfo` | `/v3/upstream/Badges/v2/sendRequestInfo` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v3/checkGreenPass` | `/v3/upstream/Badges/v3/checkGreenPass` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v3/checkGreenPassMobile` | `/v3/upstream/Badges/v3/checkGreenPassMobile` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v3/checkGreenPassNoScan` | `/v3/upstream/Badges/v3/checkGreenPassNoScan` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v3/checkOperator` | `/v3/upstream/Badges/v3/checkOperator` | Basic legacy / Bearer migrazione |
| POST | `/Badges/v3/checkQrCode` | `/v3/upstream/Badges/v3/checkQrCode` | Basic legacy / Bearer migrazione |
| DELETE | `/Badges/v3/greenPassRemove` | `/v3/upstream/Badges/v3/greenPassRemove` | Basic legacy / Bearer migrazione |
| GET | `/Badges/v3/greenPassStatus` | `/v3/upstream/Badges/v3/greenPassStatus` | Basic legacy / Bearer migrazione |
| GET | `/Badges/v3/listGreenPass` | `/v3/upstream/Badges/v3/listGreenPass` | Pubblica |

## Bus — 2 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| GET | `/Bus/v1/bus/{sede}` | `/v3/upstream/Bus/v1/bus/{sede}` | Pubblica |
| GET | `/Bus/v1/orari/{sede}` | `/v3/upstream/Bus/v1/orari/{sede}` | Pubblica |

## Eating — 6 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| POST | `/Eating/v1/addMenu` | `/v3/upstream/Eating/v1/addMenu` | Basic legacy / Bearer migrazione |
| GET | `/Eating/v1/getAllToday` | `/v3/upstream/Eating/v1/getAllToday` | Pubblica |
| GET | `/Eating/v1/getMenuBar` | `/v3/upstream/Eating/v1/getMenuBar` | Basic legacy / Bearer migrazione |
| POST | `/Eating/v1/newRisto` | `/v3/upstream/Eating/v1/newRisto` | Basic legacy / Bearer migrazione |
| POST | `/Eating/v1/newUser` | `/v3/upstream/Eating/v1/newUser` | Basic legacy / Bearer migrazione |
| GET | `/Eating/v1/removeMenu/{id}` | `/v3/upstream/Eating/v1/removeMenu/{id}` | Basic legacy / Bearer migrazione |

## GAUniparthenope — 19 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| POST | `/GAUniparthenope/v1/ReservationByProf` | `/v3/upstream/GAUniparthenope/v1/ReservationByProf` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v1/Reservations` | `/v3/upstream/GAUniparthenope/v1/Reservations` | Basic legacy / Bearer migrazione |
| POST | `/GAUniparthenope/v1/Reservations` | `/v3/upstream/GAUniparthenope/v1/Reservations` | Basic legacy / Bearer migrazione |
| DELETE | `/GAUniparthenope/v1/Reservations/{id_prenotazione}` | `/v3/upstream/GAUniparthenope/v1/Reservations/{id_prenotazione}` | Basic legacy / Bearer migrazione |
| POST | `/GAUniparthenope/v1/ServicesReservation` | `/v3/upstream/GAUniparthenope/v1/ServicesReservation` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v1/getEvents` | `/v3/upstream/GAUniparthenope/v1/getEvents` | Pubblica |
| GET | `/GAUniparthenope/v1/getLectures/{matId}` | `/v3/upstream/GAUniparthenope/v1/getLectures/{matId}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v1/getProfLectures/{aaId}` | `/v3/upstream/GAUniparthenope/v1/getProfLectures/{aaId}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v1/getStudentsList/{id_lezione}` | `/v3/upstream/GAUniparthenope/v1/getStudentsList/{id_lezione}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v1/getTodayLecture/{matId}` | `/v3/upstream/GAUniparthenope/v1/getTodayLecture/{matId}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v1/getTodayServices` | `/v3/upstream/GAUniparthenope/v1/getTodayServices` | Basic legacy / Bearer migrazione |
| POST | `/GAUniparthenope/v2/RoomsReservation` | `/v3/upstream/GAUniparthenope/v2/RoomsReservation` | Basic legacy / Bearer migrazione |
| DELETE | `/GAUniparthenope/v2/RoomsReservation/{id_prenotazione}` | `/v3/upstream/GAUniparthenope/v2/RoomsReservation/{id_prenotazione}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v2/WeekReservationReport/{days}` | `/v3/upstream/GAUniparthenope/v2/WeekReservationReport/{days}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v2/checkStudentsPresence/{id_lezione}/{building}/{start_time}/{end_time}` | `/v3/upstream/GAUniparthenope/v2/checkStudentsPresence/{id_lezione}/{building}/{start_time}/{end_time}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v2/getAllGACourses` | `/v3/upstream/GAUniparthenope/v2/getAllGACourses` | Pubblica |
| GET | `/GAUniparthenope/v2/getAllTodayRooms` | `/v3/upstream/GAUniparthenope/v2/getAllTodayRooms` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v2/getCourseLectures/{type}` | `/v3/upstream/GAUniparthenope/v2/getCourseLectures/{type}` | Basic legacy / Bearer migrazione |
| GET | `/GAUniparthenope/v2/getStudentsListCSV/{id_lezione}` | `/v3/upstream/GAUniparthenope/v2/getStudentsListCSV/{id_lezione}` | Basic legacy / Bearer migrazione |

## Notifications — 5 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| GET | `/Notifications/v1/getCdsId` | `/v3/upstream/Notifications/v1/getCdsId` | Pubblica |
| POST | `/Notifications/v1/notificationByCdsId` | `/v3/upstream/Notifications/v1/notificationByCdsId` | Basic legacy / Bearer migrazione |
| POST | `/Notifications/v1/notificationByUsername` | `/v3/upstream/Notifications/v1/notificationByUsername` | Basic legacy / Bearer migrazione |
| POST | `/Notifications/v1/registerDevice` | `/v3/upstream/Notifications/v1/registerDevice` | Basic legacy / Bearer migrazione |
| POST | `/Notifications/v1/unregisterDevice` | `/v3/upstream/Notifications/v1/unregisterDevice` | Basic legacy / Bearer migrazione |

## Reports — 1 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| POST | `/Reports/v1/getCSV` | `/v3/upstream/Reports/v1/getCSV` | Basic legacy / Bearer migrazione |

## UniparthenopeApp — 32 operazioni

| Metodo | Indirizzo originale invariato | Namespace v3 opzionale | Auth |
|---|---|---|---|
| GET | `/UniparthenopeApp/v1/general/anagrafica/{Id}` | `/v3/upstream/UniparthenopeApp/v1/general/anagrafica/{Id}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/general/avvisi/{size}` | `/v3/upstream/UniparthenopeApp/v1/general/avvisi/{size}` | Pubblica |
| GET | `/UniparthenopeApp/v1/general/current_aa/{cdsId}` | `/v3/upstream/UniparthenopeApp/v1/general/current_aa/{cdsId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/general/image/{personId}` | `/v3/upstream/UniparthenopeApp/v1/general/image/{personId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/general/image_prof/{idAb}` | `/v3/upstream/UniparthenopeApp/v1/general/image_prof/{idAb}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/general/infoCourse/{adLogId}` | `/v3/upstream/UniparthenopeApp/v1/general/infoCourse/{adLogId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/general/news/{size}` | `/v3/upstream/UniparthenopeApp/v1/general/news/{size}` | Pubblica |
| GET | `/UniparthenopeApp/v1/general/persone/{nome_completo}` | `/v3/upstream/UniparthenopeApp/v1/general/persone/{nome_completo}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/general/privacy` | `/v3/upstream/UniparthenopeApp/v1/general/privacy` | Pubblica |
| GET | `/UniparthenopeApp/v1/general/recentAD/{adId}` | `/v3/upstream/UniparthenopeApp/v1/general/recentAD/{adId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/general/sedi` | `/v3/upstream/UniparthenopeApp/v1/general/sedi` | Pubblica |
| GET | `/UniparthenopeApp/v1/login` | `/v3/upstream/UniparthenopeApp/v1/login` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/logout` | `/v3/upstream/UniparthenopeApp/v1/logout` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/professor/detailedInfo/{docenteId}` | `/v3/upstream/UniparthenopeApp/v1/professor/detailedInfo/{docenteId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/professor/getCourses/{aaId}` | `/v3/upstream/UniparthenopeApp/v1/professor/getCourses/{aaId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/professor/getSession` | `/v3/upstream/UniparthenopeApp/v1/professor/getSession` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/professor/getStudentList/{cdsId}/{adId}/{appId}` | `/v3/upstream/UniparthenopeApp/v1/professor/getStudentList/{cdsId}/{adId}/{appId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/average/{matId}/{value}` | `/v3/upstream/UniparthenopeApp/v1/students/average/{matId}/{value}` | Basic legacy / Bearer migrazione |
| POST | `/UniparthenopeApp/v1/students/bookExam/{cdsId}/{adId}/{appId}` | `/v3/upstream/UniparthenopeApp/v1/students/bookExam/{cdsId}/{adId}/{appId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/checkAppello/{cdsId}/{adId}` | `/v3/upstream/UniparthenopeApp/v1/students/checkAppello/{cdsId}/{adId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/checkExams/{matId}/{adsceId}` | `/v3/upstream/UniparthenopeApp/v1/students/checkExams/{matId}/{adsceId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/checkPrenotazione/{cdsId}/{adId}/{appId}/{stuId}` | `/v3/upstream/UniparthenopeApp/v1/students/checkPrenotazione/{cdsId}/{adId}/{appId}/{stuId}` | Basic legacy / Bearer migrazione |
| DELETE | `/UniparthenopeApp/v1/students/deleteExam/{cdsId}/{adId}/{appId}/{stuId}` | `/v3/upstream/UniparthenopeApp/v1/students/deleteExam/{cdsId}/{adId}/{appId}/{stuId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/departmentInfo/{stuId}` | `/v3/upstream/UniparthenopeApp/v1/students/departmentInfo/{stuId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/exams/{stuId}/{pianoId}` | `/v3/upstream/UniparthenopeApp/v1/students/exams/{stuId}/{pianoId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/getProfessors/{aaId}/{cdsId}` | `/v3/upstream/UniparthenopeApp/v1/students/getProfessors/{aaId}/{cdsId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/getReservations/{matId}` | `/v3/upstream/UniparthenopeApp/v1/students/getReservations/{matId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/pianoId/{stuId}` | `/v3/upstream/UniparthenopeApp/v1/students/pianoId/{stuId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/taxes/{persId}` | `/v3/upstream/UniparthenopeApp/v1/students/taxes/{persId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v1/students/totalExams/{matId}` | `/v3/upstream/UniparthenopeApp/v1/students/totalExams/{matId}` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v2/login` | `/v3/upstream/UniparthenopeApp/v2/login` | Basic legacy / Bearer migrazione |
| GET | `/UniparthenopeApp/v2/students/myExams/{matId}` | `/v3/upstream/UniparthenopeApp/v2/students/myExams/{matId}` | Basic legacy / Bearer migrazione |


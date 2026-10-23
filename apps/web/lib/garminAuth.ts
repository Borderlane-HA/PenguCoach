// Pure helpers for the Garmin connection methods. No DOM access: unit-tested in node.
export type Lang = "de" | "en";
export type AuthMode = "password" | "personal_api";
export type PersonalApiInfo = {key_settings_url?:string;key_hint?:string|null;expires_on?:string|null;days_left?:number|null;expiring?:boolean};

export const KEY_SETTINGS_URL = "https://connect.garmin.com/app/settings/personalApiToken";

const ERRORS:Record<string,[string,string]> = {
  GARMIN_API_KEY_REJECTED:["Garmin hat den API-Key abgelehnt. Prüfe, ob er vollständig kopiert, noch gültig und nicht widerrufen ist.","Garmin rejected the API key. Check that it was copied completely, is still valid and has not been revoked."],
  GARMIN_API_KEY_EXPIRED:["Das Ablaufdatum liegt in der Vergangenheit. Erstelle in Garmin Connect einen neuen Key.","The expiry date is in the past. Create a new key in Garmin Connect."],
  GARMIN_API_TOKEN_INVALID:["Garmin hat keine gültige Antwort geliefert. Bitte später erneut versuchen.","Garmin returned an invalid answer. Please try again later."],
  GARMIN_API_UNREACHABLE:["Die Garmin Personal API ist gerade nicht erreichbar. Bitte später erneut versuchen.","The Garmin Personal API is currently unreachable. Please try again later."],
  GARMIN_RATE_LIMITED:["Garmin begrenzt gerade die Anfragen. Bitte in einigen Minuten erneut versuchen.","Garmin is limiting requests right now. Please try again in a few minutes."],
  GARMIN_AUTH_FAILED:["Anmeldung fehlgeschlagen. Prüfe E-Mail und Passwort.","Sign-in failed. Check e-mail and password."],
  GARMIN_MFA_FAILED:["Der Bestätigungscode wurde nicht akzeptiert.","The verification code was not accepted."],
  GARMIN_MFA_CHALLENGE_EXPIRED:["Die Bestätigung ist abgelaufen. Bitte erneut anmelden.","The verification expired. Please sign in again."],
  GARMIN_WORKOUT_EXPORT_NEEDS_LOGIN:["Workouts zu Garmin übertragen oder dort löschen braucht den Garmin-Login – als Verbindungsart oder als Zusatz-Login neben dem API-Key (Einstellungen → Garmin → Training & Kalender).","Sending workouts to Garmin or deleting them there needs the Garmin login – as connection method or as extra login next to the API key (Settings → Garmin → Training & calendar)."],
  GARMIN_EXPORT_LOGIN_EXPIRED:["Der Garmin-Login für den Workout-Export ist abgelaufen. Melde dich unter Einstellungen → Garmin → Training & Kalender neu an. Der Datensync über den API-Key läuft weiter.","The Garmin login for workout export has expired. Sign in again under Settings → Garmin → Training & calendar. The data sync via the API key keeps running."],
  GARMIN_EXPORT_NEEDS_API_CONNECTION:["Der Zusatz-Login für den Export ist nur mit einer aktiven Personal-API-Verbindung möglich.","The extra export login requires an active Personal API connection."],
  GARMIN_REAUTH_REQUIRED:["Garmin verlangt eine neue Anmeldung bzw. einen neuen API-Key.","Garmin requires a new sign-in or a new API key."],
};

export function garminError(code:string,lang:Lang){
  const http=/^GARMIN_API_HTTP_(\d{3})$/.exec(code);
  if(http)return lang==="de"?`Garmin hat mit HTTP ${http[1]} geantwortet. Bitte später erneut versuchen.`:`Garmin answered with HTTP ${http[1]}. Please try again later.`;
  const hit=ERRORS[code];
  return hit?hit[lang==="de"?0:1]:code;
}

/** Status line for the stored key: hint plus expiry, with a warning level. */
export function keyStatus(info:PersonalApiInfo|undefined|null,lang:Lang){
  const de=lang==="de",hint=info?.key_hint??"";
  const days=typeof info?.days_left==="number"?info.days_left:null;
  if(days===null)return {level:"info" as const,text:de?`API-Key ${hint} · Ablaufdatum unbekannt – trage es beim nächsten Key mit ein, dann erinnert PenguCoach dich rechtzeitig.`:`API key ${hint} · expiry unknown – add it with the next key and PenguCoach reminds you in time.`};
  const when=info?.expires_on?new Date(`${info.expires_on}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB"):"";
  if(days<0)return {level:"error" as const,text:de?`API-Key ${hint} ist seit ${when} abgelaufen. Erstelle einen neuen Key.`:`API key ${hint} expired on ${when}. Create a new key.`};
  if(days<=14)return {level:"warn" as const,text:de?`API-Key ${hint} läuft ${days===0?"heute":days===1?"morgen":`in ${days} Tagen`} ab (${when}). Jetzt erneuern.`:`API key ${hint} expires ${days===0?"today":days===1?"tomorrow":`in ${days} days`} (${when}). Renew it now.`};
  return {level:"ok" as const,text:de?`API-Key ${hint} · gültig bis ${when}`:`API key ${hint} · valid until ${when}`};
}

/** ISO date `months` after `from` (local calendar), used for the expiry presets. */
export function addMonths(from:Date,months:number){
  const d=new Date(from.getFullYear(),from.getMonth()+months,from.getDate(),12);
  if(d.getDate()!==from.getDate())d.setDate(0);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

/** Keys are long single tokens; strip whitespace and an accidental "ApiKey " prefix from pasting. */
export function cleanKey(value:string){
  return value.replace(/^\s*(ApiKey|Bearer)\s+/i,"").replace(/\s+/g,"");
}

export type Capability={key:string;de:string;en:string;password:boolean;personal:boolean|"optional"};
export const CAPABILITIES:Capability[]=[
  {key:"activities",de:"Aktivitäten & Original-FIT",en:"Activities & original FIT",password:true,personal:true},
  {key:"daily",de:"Tageswerte, Schlaf, HRV, Stress, Body Battery",en:"Daily values, sleep, HRV, stress, Body Battery",password:true,personal:true},
  {key:"body",de:"Gewicht & Körperdaten, Herzfrequenzzonen",en:"Weight & body data, heart-rate zones",password:true,personal:true},
  {key:"training",de:"Trainingsstatus, Readiness, VO₂max-Verlauf, Leistungszonen",en:"Training status, readiness, VO₂max trend, power zones",password:true,personal:false},
  {key:"export",de:"Workouts zu Garmin übertragen",en:"Send workouts to Garmin",password:true,personal:"optional"},
];

/** Features the Personal API does not deliver. Used to grey out cards with a hint. */
export type GarminFeature="training_readiness"|"training_status"|"power_zones"|"workout_export";
export type GarminModeInfo={auth_mode?:AuthMode|null;connected?:boolean;export_login?:{connected?:boolean}|null};

export function featureUnavailable(info:GarminModeInfo|null|undefined,feature:GarminFeature){
  if(!info||info.auth_mode!=="personal_api"||!info.connected)return false;
  if(feature==="workout_export")return !info.export_login?.connected;
  return true;
}

export function featureHint(feature:GarminFeature,lang:Lang){
  const de=lang==="de";
  if(feature==="workout_export")return de?"Mit dem Garmin API-Key allein nicht möglich – unter Einstellungen → Garmin zusätzlich den Garmin-Login für den Export hinterlegen.":"Not possible with the Garmin API key alone – add the Garmin login for export under Settings → Garmin.";
  const name=feature==="training_readiness"?(de?"Training Readiness":"Training readiness"):feature==="power_zones"?(de?"Leistungszonen":"Power zones"):(de?"Trainingsstatus":"Training status");
  return de?`${name}: über den Garmin API-Key nicht verfügbar. Dafür die Verbindungsart „Garmin-Login“ verwenden.`:`${name}: not available through the Garmin API key. Use the “Garmin login” connection method for this.`;
}

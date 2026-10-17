import {bi,type Lang} from "./i18n";
export function strengthPrescription(ex:Record<string,any>,lang:Lang){
 if(ex.duration_seconds!=null)return `${ex.duration_seconds} s`;
 if(ex.reps_in_reserve!=null)return `max − ${ex.reps_in_reserve} ${bi(lang,"Wdh.","reps")}`;
 return ex.reps_max!=null?`${ex.reps}–${ex.reps_max}`:String(ex.reps??"—");
}

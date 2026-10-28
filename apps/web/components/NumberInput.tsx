"use client";

import {useEffect,useRef,useState,type InputHTMLAttributes} from "react";
import {useI18n} from "../lib/i18n";
import {allowsDecimal,normalizeNumberDraft,parseNumberDraft,validNumberDraft} from "../lib/numberInput";

type Props=Omit<InputHTMLAttributes<HTMLInputElement>,"type"|"value"|"defaultValue"|"onChange">&{
  value:string|number|null|undefined;
  onValueChange:(value:string)=>void;
  allowEmpty?:boolean;
};

export default function NumberInput({value,onValueChange,allowEmpty=false,min,max,step=1,onFocus,onBlur,onKeyDown,inputMode,...rest}:Props){
  const {lang}=useI18n();
  const text=value==null?"":String(value);
  const [draft,setDraft]=useState(text);
  const focused=useRef(false),emitted=useRef(text),input=useRef<HTMLInputElement>(null);
  const limits={min,max,step,allowEmpty};
  const valid=validNumberDraft(draft,limits);
  useEffect(()=>{
    // Preserve the caret, empty values and a typed decimal separator. Still
    // accept external changes, e.g. model/profile presets or a form reset.
    if(!focused.current||text!==emitted.current)setDraft(text);
    emitted.current=text;
  },[text]);
  useEffect(()=>{
    input.current?.setCustomValidity(valid?"":lang==="en"?"Please enter a valid number within the allowed range.":"Bitte eine gültige Zahl im erlaubten Bereich eingeben.");
  },[valid,lang]);
  function publish(next:string){emitted.current=next;onValueChange(next)}
  function commit(){
    const next=normalizeNumberDraft(draft,text,limits);
    setDraft(next);
    if(validNumberDraft(next,limits)){
      input.current?.setCustomValidity("");
      if(next!==text)publish(next);
    }
  }
  const parsed=parseNumberDraft(draft);
  return <input {...rest} ref={input} type="text" role="spinbutton" inputMode={inputMode??(allowsDecimal(limits)?"decimal":"numeric")}
    min={min} max={max} step={step} value={draft} aria-valuemin={min===undefined?undefined:Number(min)} aria-valuemax={max===undefined?undefined:Number(max)} aria-valuenow={parsed??undefined} aria-invalid={!valid||undefined}
    onFocus={event=>{focused.current=true;onFocus?.(event)}}
    onChange={event=>{
      const next=event.target.value;setDraft(next);
      // Only complete, in-range values reach application state. Required
      // fields may be empty while editing; optional fields can be cleared.
      if(validNumberDraft(next,limits))publish(next.trim()===""?"":String(parseNumberDraft(next)));
    }}
    onBlur={event=>{focused.current=false;commit();onBlur?.(event)}}
    onKeyDown={event=>{
      if(event.key==="Enter")commit();
      if((event.key==="ArrowUp"||event.key==="ArrowDown")&&!rest.readOnly&&!rest.disabled){
        event.preventDefault();
        const increment=step==="any"?1:Number(step);
        const next=normalizeNumberDraft(String((parsed??parseNumberDraft(text)??0)+(event.key==="ArrowUp"?increment:-increment)),text,limits);
        setDraft(next);publish(next);
      }
      onKeyDown?.(event);
    }}/>
}

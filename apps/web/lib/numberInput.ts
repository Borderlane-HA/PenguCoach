export type NumberLimits={min?:number|string;max?:number|string;step?:number|string;allowEmpty?:boolean};

export function parseNumberDraft(raw:string):number|null{
  const text=raw.trim();
  if(!/^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$/.test(text))return null;
  const value=Number(text.replace(",","."));
  return Number.isFinite(value)?value:null;
}

export function allowsDecimal({step=1}:NumberLimits):boolean{
  return step==="any"||!Number.isInteger(Number(step));
}

export function validNumberDraft(raw:string,limits:NumberLimits):boolean{
  if(raw.trim()==="")return Boolean(limits.allowEmpty);
  const value=parseNumberDraft(raw);
  return value!==null&&(allowsDecimal(limits)||Number.isInteger(value))
    &&(limits.min===undefined||value>=Number(limits.min))
    &&(limits.max===undefined||value<=Number(limits.max));
}

// Bounds apply when editing finishes. A blank required field returns to the
// last accepted value, never to a minimum inserted between keystrokes.
export function normalizeNumberDraft(raw:string,fallback:string,limits:NumberLimits):string{
  if(raw.trim()===""&&limits.allowEmpty)return "";
  let value=parseNumberDraft(raw);
  if(value===null)return fallback;
  if(!allowsDecimal(limits))value=Math.round(value);
  if(limits.min!==undefined)value=Math.max(Number(limits.min),value);
  if(limits.max!==undefined)value=Math.min(Number(limits.max),value);
  return String(Number(value.toFixed(12)));
}

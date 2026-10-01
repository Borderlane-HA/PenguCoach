export type AiModelCost={
  input_cost_per_million_eur?:number|null;
  output_cost_per_million_eur?:number|null;
};

export type QualityId="very_low"|"low"|"standard"|"high";

export const QUALITY_IDS:QualityId[]=["very_low","low","standard","high"];

export function qualityLabel(id:QualityId,de:boolean){
  return ({very_low:de?"Sehr niedrig":"Very low",low:de?"Niedrig":"Low",standard:de?"Standard":"Standard",high:de?"Hoch":"High"})[id];
}

export function qualityHint(id:QualityId,de:boolean){
  return ({
    very_low:de?"Maximal kompakt · günstigste Ausgabe":"Maximally concise · lowest output cost",
    low:de?"Kompakt · Fokus auf das Wesentliche":"Concise · focused on essentials",
    standard:de?"Ausgewogen · bisheriges Verhalten":"Balanced · previous behavior",
    high:de?"Ausführlicher · mehr Begründung":"More detailed · more rationale",
  })[id];
}

export function hasPricing(model:AiModelCost|undefined|null){
  return model?.input_cost_per_million_eur!=null||model?.output_cost_per_million_eur!=null;
}

export function costForTokens(model:AiModelCost|undefined|null,inputTokens:number,outputTokens:number){
  if(!hasPricing(model))return null;
  return inputTokens*Number(model?.input_cost_per_million_eur??0)/1_000_000+outputTokens*Number(model?.output_cost_per_million_eur??0)/1_000_000;
}

export function estimatedMaxCost(model:AiModelCost|undefined|null,contextWindow:number,maxOutput:number,calls=1){
  const input=Math.max(256,contextWindow-maxOutput-768);
  const one=costForTokens(model,input,maxOutput);
  return one==null?null:one*Math.max(1,calls);
}

export function euro(value:number|null|undefined){
  if(value==null||!Number.isFinite(value))return "—";
  if(value===0)return "0,00 €";
  const digits=value<0.01?4:2;
  return `${value.toLocaleString("de-DE",{minimumFractionDigits:digits,maximumFractionDigits:digits})} €`;
}

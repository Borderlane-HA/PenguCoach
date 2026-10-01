export type PricePeriod={id:number;amount:number;valid_from:string;valid_to:string|null}
export type Expense={id:number;name:string;provider:string;entry_type:'expense'|'income';amount:number;currency:string;billing_interval:string;interval_months:number;monthly_equivalent:number;yearly_equivalent:number;category_id:number|null;category:string|null;category_color:string;account_id:number|null;account:string|null;start_date:string|null;next_due_date:string|null;contract_end:string|null;effective_contract_end:string|null;cancellation_date:string|null;effective_cancellation_date:string|null;minimum_term_months:number|null;renewal_period_months:number|null;cancellation_notice_days:number|null;cancelled_on:string|null;auto_renew:boolean;status:string;essential:boolean;tags:string;notes:string;price_history:PricePeriod[];next_price_change:{amount:number;valid_from:string}|null}
export type Account={id:number;name:string;kind:string;note:string}
export type Category={id:number;name:string;icon:string;color:string}
export type User={id:number;username:string;display_name:string;role:string;is_active?:boolean;version?:string}
export type AIProvider={id:string;label:string;default_base_url:string;key_optional:boolean}
export type AIProfile={id:number;name:string;provider:string;provider_label:string;model:string;enabled:boolean;base_url?:string;has_api_key?:boolean}
export type AIMessage={id:number;role:'user'|'assistant';content:string;created_at:string}
export type AIConversation={id:number;profile_id:number|null;title:string;mode:'analysis'|'savings'|'chat';target_savings:number|null;selected_expense_ids:number[];status:'idle'|'running'|'error';last_error:string;created_at:string;updated_at:string;messages?:AIMessage[]}
export type AIBrain={summary:string;updated_at:string|null}
export type UserPreferences={language:'de'|'en';ai_prompt:string;theme:string}

export async function api<T=any>(url:string,options:RequestInit={}):Promise<T>{
 const r=await fetch(url,{credentials:'include',headers:{'Content-Type':'application/json',...(options.headers||{})},...options})
 if(!r.ok){let m=`HTTP ${r.status}`;try{const j=await r.json();m=j.detail||m}catch{};throw new Error(m)}
 return r.status===204?undefined as T:await r.json()
}
const locale=()=>document.documentElement.lang==='en'?'en-GB':'de-DE';
export const money=(v:number,c='EUR')=>new Intl.NumberFormat(locale(),{style:'currency',currency:c}).format(v)
export const dateFmt=(v?:string|null)=>v?new Intl.DateTimeFormat(locale()).format(new Date(v+'T12:00:00')):'–'

export type ReminderItem={expense_id:number;name:string;provider:string;kind:'cancellation_due'|'renewal_risk'|'auto_renewed';label:string;event_key:string;cancellation_date:string|null;contract_end:string|null;days_remaining:number|null;cancelled_on:string|null;auto_renew:boolean;renewal_period_months:number|null;category:string|null;category_color:string}
export type RemindersResponse={count:number;reminder_days:number;items:ReminderItem[]}

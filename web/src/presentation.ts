type MessageSnapshot = {id:string;revision:number;messages:{id:string}[]};

export function newMessageIds(previous:MessageSnapshot|null,next:MessageSnapshot):string[] {
  if(!previous||previous.id!==next.id)return [];
  const known=new Set(previous.messages.map(message=>message.id));
  return next.messages.filter(message=>!known.has(message.id)).map(message=>message.id);
}

export function acceptSnapshot(previous:MessageSnapshot|null,next:MessageSnapshot,active:string|null):boolean {
  return next.id===active&&(!previous||previous.id!==next.id||next.revision>=previous.revision);
}

export function draftAfterSend(current:string,sent:string,active:string|null,session:string):string {
  return active===session&&current===sent?'':current;
}

export function scrollBehavior(reduced:boolean,initial=false):ScrollBehavior {
  return reduced||initial?'instant':'smooth';
}

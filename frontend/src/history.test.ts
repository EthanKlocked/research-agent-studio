import { describe,it,expect } from "vitest";
import { mergeEvents } from "./state";
import { snapshot } from "./test/fixtures";
import type {RunEvent} from "./types";
const s=snapshot({last_seq:200});
const event=(seq:number,run_id=s.run_id):RunEvent=>({seq,run_id,type:"model_complete",timestamp:s.started_at,data:{snapshot:{...s,run_id,last_seq:seq}}});
describe("bounded restored timeline",()=>{
  it("deduplicates by run/sequence, orders history and rejects foreign/future events",()=>{
    const merged=mergeEvents([event(199),event(200)],[event(198),event(199),event(201),event(197,"other")],s);
    expect(merged.map(e=>e.seq)).toEqual([198,199,200]);
  });
  it("retains only 150 most recent entries without changing cost summary",()=>{
    expect(mergeEvents([],Array.from({length:200},(_,i)=>event(i+1)),s).map(e=>e.seq)).toEqual(Array.from({length:150},(_,i)=>i+51));
    expect(s.cost_summary).toBeUndefined();
  });
});

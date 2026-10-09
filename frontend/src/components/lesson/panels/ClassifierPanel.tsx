import { useState } from 'react'
import { useParams, Link } from 'react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, RefreshCw, RotateCcw } from 'lucide-react'
import { api, unwrap, errorMessage, type Schemas } from '@/api/client'
import { useClassifier } from '@/api/classifier'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { Modal } from '@/components/ui/modal'
import { ConfirmDialog } from '@/components/ui/dialog'

type Cell = Schemas['ClassifierCell']
const names: Record<string,string> = {relevance:'Rilevanza',question_types:'Tipo di domanda',exercises:'Esercizi',cases:'Casi clinici',prefilter:'Prefiltro errori',drift:'Deriva dal trascritto',enrichment:'Arricchimento'}
const values: Record<string,string> = {didactic:'Didattica',organizational:'Organizzativa',no_content:'Senza contenuto',quiz:'Quiz',mirata:'Mirata',caso:'Caso clinico',esercizio:'Esercizio',nessuno:'Nessuno',svolto:'Svolto',continua:'Continua il precedente',esplicito:'Esplicito',adattabile:'Si presta',skip_review:'Corretta, salta la revisione',review:'Da rivedere',drift:'Possibile invenzione',coherent:'Coerente',none:'Nessuno',infographic:'Infografica',visualization:'Visualizzazione'}
const states: Record<string,string> = {done:'Fatto',partial:'Parziale',stale:'Da rifare',never:'Mai',off:'Spento',fresh:'Fatto',missing:'Da classificare',error:'Errore',skipped:'Saltata'}
export function ClassifierPanel({ lessonId }: {lessonId?:number}) {
 const params=useParams()
 const id=lessonId??Number(params.lessonId)
 const query=useClassifier(id)
 const client=useQueryClient()
 const [hover,setHover]=useState<string|null>(null)
 const [selection,setSelection]=useState<{job:string;index:number}|null>(null)
 const [confirm,setConfirm]=useState<{job?:string}|null>(null)
 const invalidate=()=> {void client.invalidateQueries({queryKey:['classifier',id]});void client.invalidateQueries({queryKey:['relevance',id]});void client.invalidateQueries({queryKey:['lesson',id]});void client.invalidateQueries({queryKey:['recall-units',id]})}
 const run=useMutation({mutationFn:({job,force=false,unit_ids}:{job?:string;force?:boolean;unit_ids?:string[]})=>job?unwrap(api.POST('/api/v1/lessons/{lesson_id}/classifier/{job}/run',{params:{path:{lesson_id:id,job}},body:{force,unit_ids}})):unwrap(api.POST('/api/v1/lessons/{lesson_id}/classifier/run',{params:{path:{lesson_id:id}},body:{force,unit_ids}})),onSuccess:invalidate})
 const update=useMutation({mutationFn:({job,cell,value}:{job:string;cell:Cell;value:string|null})=>unwrap(api.PUT('/api/v1/lessons/{lesson_id}/classifier/{job}/{cell_id}',{params:{path:{lesson_id:id,job,cell_id:cell.unit_id??cell.section_id??''}},body:{value}})),onSuccess:saved=>{client.setQueryData(['classifier',id],saved);invalidate()}})
 if(query.isPending)return <p className="text-meta text-muted-foreground">Carico le classificazioni…</p>
 if(query.isError)return <Alert tone="danger">{errorMessage(query.error)}</Alert>
 const data=query.data
 if(!data)return null
 const selected=selection?data.jobs[selection.job]?.cells[selection.index]:null
 const ids=(cell:Cell)=>cell.unit_id?[cell.unit_id]:data.units.filter(u=>u.section_id===cell.section_id).map(u=>u.id)
 const title=(cell:Cell)=>{const unit=data.units.find(u=>u.id===ids(cell)[0]);return `${cell.unit_id??cell.section_id} · ${unit?.title??''}`}
 const value=(cell:Cell)=>cell.value?values[cell.value]??cell.value:states[cell.state]
 const actions=(job?:string)=><div className="flex"><IconButton icon={RefreshCw} label={job?`Classifica le cambiate: ${names[job]}`:'Classifica le cambiate'} unavailable={run.isPending?'Job in coda':null} onClick={()=>run.mutate({job})}/><IconButton icon={RotateCcw} label={job?`Riclassifica tutte: ${names[job]}`:'Riclassifica tutte'} unavailable={run.isPending?'Job in coda':null} onClick={()=>setConfirm({job})}/></div>
 return <div className="flex flex-col gap-4" data-testid="classifier-panel">
   <div className="flex items-center justify-between gap-2"><p className="text-meta">{data.pending} unità da rivedere</p>{actions()}</div>
   {(run.isError||update.isError)&&<Alert tone="danger">{errorMessage(run.error??update.error)}</Alert>}
   {run.isSuccess&&<p role="status" className="text-meta">Classificazione in coda.</p>}
   <div className="rt-cls-grid-scroll">
   {Object.entries(names).map(([job,name])=>{const block=data.jobs[job];if(!block||block.mode==='off')return null;return <section key={job} className="mb-4" data-testid={`classifier-job-${job}`}>
    <div className="flex items-center gap-2"><h3 className="min-w-0 flex-1 text-body font-semibold">{name}</h3><span className="text-meta text-muted-foreground">{states[block.state]}{block.mode==='observe'?' · In osservazione':block.mode==='manual'?' · Manuale':''}</span>{actions(job)}</div>
    <div className="rt-cls-grid" style={{gridTemplateColumns:`repeat(${Math.max(1,data.units.length)}, minmax(18px, 1fr))`}}>
     {block.cells.map((cell,index)=>{const cellIds=ids(cell);const column=data.units.findIndex(u=>u.id===cellIds[0])+1;const label=`${name} · ${title(cell)} · ${value(cell)}`;return <Tooltip key={cell.unit_id??cell.section_id} content={label}>{trigger=><button {...trigger} aria-label={label} data-testid={`classifier-cell-${job}-${cell.unit_id??cell.section_id}`} data-state={cell.state} data-manual={cell.source==='manual'} data-value={cell.value??''} className={`rt-cls-cell ${hover&&cellIds.includes(hover)?'rt-cls-hover':''}`} style={{gridColumn:`${column} / span ${Math.max(1,cellIds.length)}`}} onMouseEnter={()=>{trigger.onMouseEnter();setHover(cellIds[0]??null)}} onMouseLeave={()=>{trigger.onMouseLeave();setHover(null)}} onFocus={()=>{trigger.onFocus();setHover(cellIds[0]??null)}} onBlur={()=>{trigger.onBlur();setHover(null)}} onClick={()=>setSelection({job,index})}>{cell.source==='manual'&&<span className="rt-cls-manual" aria-label="Corretta a mano"/>}<span className="sr-only">{value(cell)}</span></button>}</Tooltip>})}
    </div>
   </section>})}
   </div>
   <Modal open={!!selected} onClose={()=>setSelection(null)} title={selected&&selection?`${names[selection.job]} · ${title(selected)}`:''} className="rt-cls-sheet" testId="classifier-sheet">
    {selected&&selection&&<div className="flex flex-col gap-3 pt-3"><p className="text-meta">{value(selected)} · {states[selected.state]}</p><div className="flex flex-wrap gap-2">{(selected.options ?? []).map(option=><Button key={option} variant={selected.value===option?'default':'outline'} disabled={update.isPending} onClick={()=>update.mutate({job:selection.job,cell:selected,value:option})}>{values[option]??option}</Button>)}</div>
    {!!selected.options?.length&&<Button variant="ghost" disabled={update.isPending} onClick={()=>update.mutate({job:selection.job,cell:selected,value:null})}>Torna al classificatore</Button>}
    <Button variant="outline" onClick={()=>run.mutate({job:selection.job,force:true,unit_ids:ids(selected)})}>Riclassifica questa</Button>
    <Link className={buttonVariants({ variant: "outline" })} to={`/lezioni/${id}#unit-${ids(selected)[0]}`} onClick={()=>setSelection(null)}>Vai all’unità</Link>
    <div className="flex justify-between"><IconButton icon={ChevronLeft} label="Subunità precedente" unavailable={selection.index===0?'Prima subunità':null} onClick={()=>setSelection({...selection,index:selection.index-1})}/><IconButton icon={ChevronRight} label="Subunità successiva" unavailable={selection.index===data.jobs[selection.job].cells.length-1?'Ultima subunità':null} onClick={()=>setSelection({...selection,index:selection.index+1})}/></div></div>}
   </Modal>
   <ConfirmDialog open={confirm!==null} title="Riclassifica tutte" confirmLabel="Riclassifica" onCancel={()=>setConfirm(null)} onConfirm={()=>{run.mutate({job:confirm?.job,force:true});setConfirm(null)}}>Riclassificare tutte le unità{confirm?.job?` per ${names[confirm.job]}`:''}?</ConfirmDialog>
 </div>
}

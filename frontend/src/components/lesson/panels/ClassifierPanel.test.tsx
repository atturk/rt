import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { ClassifierPanel } from './ClassifierPanel'
const cell = {unit_id:'1.1',value:'didactic',source:'classifier',state:'fresh',options:['didactic','organizational']}
const overview = {units:[{id:'1.1',title:'Titolo',section_id:'1'}],pending:0,jobs:{relevance:{mode:'observe',state:'done',cells:[cell]},question_types:{mode:'off',state:'off',cells:[]},exercises:{mode:'manual',state:'never',cells:[{section_id:'1',value:null,source:'classifier',state:'missing',options:['nessuno','svolto']}]}}}
const ok = (data:unknown)=>({data,response:new Response(null,{status:200})}) as never
afterEach(()=>{cleanup();vi.restoreAllMocks()})
function setup(){vi.spyOn(api,'GET').mockResolvedValue(ok(overview));const client=new QueryClient({defaultOptions:{queries:{retry:false}}});render(<QueryClientProvider client={client}><MemoryRouter><ClassifierPanel lessonId={5}/></MemoryRouter></QueryClientProvider>);return client}
it('mostra griglie attive, apre la scheda e corregge la cella',async()=>{
 const put=vi.spyOn(api,'PUT').mockResolvedValue(ok({...overview,jobs:{...overview.jobs,relevance:{...overview.jobs.relevance,cells:[{...cell,value:'organizational',source:'manual'}]}}}))
 setup()
 expect(await screen.findByTestId('classifier-job-relevance')).toBeInTheDocument()
 expect(screen.queryByTestId('classifier-job-question_types')).toBeNull()
 expect(screen.getByTestId('classifier-job-exercises')).toBeInTheDocument()
 fireEvent.click(screen.getByTestId('classifier-cell-relevance-1.1'))
 expect(await screen.findByRole('dialog',{name:/Rilevanza · 1.1/})).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'Organizzativa'}))
 await waitFor(()=>expect(put).toHaveBeenCalledWith('/api/v1/lessons/{lesson_id}/classifier/{job}/{cell_id}',{params:{path:{lesson_id:5,job:'relevance',cell_id:'1.1'}},body:{value:'organizational'}}))
 fireEvent.click(screen.getByRole('button',{name:'Torna al classificatore'}))
 await waitFor(()=>expect(put).toHaveBeenLastCalledWith('/api/v1/lessons/{lesson_id}/classifier/{job}/{cell_id}',expect.objectContaining({body:{value:null}})))
})
it('il tooltip mostra titolo e valore e la riclassificazione chiede conferma',async()=>{
 vi.spyOn(api,'POST').mockResolvedValue(ok({job_id:'job'}))
 setup()
 const cell=await screen.findByTestId('classifier-cell-relevance-1.1')
 fireEvent.mouseEnter(cell)
 expect(await screen.findByRole('tooltip')).toHaveTextContent('Titolo · Didattica')
 fireEvent.click(screen.getByRole('button',{name:'Riclassifica tutte'}))
 expect(await screen.findByRole('dialog',{name:'Riclassifica tutte'})).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'Riclassifica'}))
 await waitFor(()=>expect(api.POST).toHaveBeenCalled())
})

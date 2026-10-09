import { expect } from '@playwright/test'
import { test, apiGet, authHeaders, loginViaLink, openLessonDetails } from './support'
test('da Dettagli corregge una cella e torna al classificatore', async ({page,request})=>{
 await loginViaLink(page)
 const previous=await apiGet<Record<string,unknown>>(request,'/settings/classifier')
 const jobs=previous.jobs as Record<string,Record<string,unknown>>
 const configured={...previous,jobs:{...jobs,relevance:{...jobs.relevance,mode:'observe'}}}
 const response=await request.put('/api/v1/settings/classifier',{headers:authHeaders(),data:configured})
 expect(response.ok()).toBeTruthy()
 try {
  const lessons=await apiGet<{id:number;phases:Record<string,string>}[]>(request,'/lessons')
  const id=lessons.find(l=>l.phases.rewrite==='VALID')!.id
  await page.goto(`/lezioni/${id}`)
  await openLessonDetails(page)
  await page.getByRole('button',{name:/Classificatore.*unità da rivedere/}).click()
  await expect(page).toHaveURL(/panel=classificatore/)
  const cell=page.locator('[data-testid^="classifier-cell-relevance-"]').first()
  await cell.click()
  const sheet=page.getByTestId('classifier-sheet')
  await sheet.getByRole('button',{name:'Organizzativa',exact:true}).click()
  await expect(cell).toHaveAttribute('data-manual','true')
  await sheet.getByRole('button',{name:'Torna al classificatore',exact:true}).click()
  await expect(cell).toHaveAttribute('data-manual','false')
 } finally {
  await page.goto('about:blank')
  const restored=await request.put('/api/v1/settings/classifier',{headers:authHeaders(),data:previous})
  expect(restored.ok()).toBeTruthy()
 }
})

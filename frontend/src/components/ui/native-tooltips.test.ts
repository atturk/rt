import ts from 'typescript'
import { expect, it } from 'vitest'

it('i componenti non usano title nativi su pulsanti e link', () => {
  const violations: string[] = []
  const sources = import.meta.glob(['../**/*.tsx', '../**/*.ts'], { query: '?raw', import: 'default', eager: true })
  for (const [path, source] of Object.entries(sources)) {
    if (path.includes('.test.')) continue
    const file = ts.createSourceFile(path, source as string, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    function visit(node: ts.Node) {
      if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && ['button', 'a', 'Link'].includes(node.tagName.getText(file))) {
        if (node.attributes.properties.some(p => ts.isJsxAttribute(p) && p.name.getText(file) === 'title')) violations.push(path)
      }
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isPropertyAccessExpression(node.left) && node.left.name.text === 'title') violations.push(path)
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'setAttribute' && node.arguments[0]?.getText(file).match(/^['"]title['"]$/)) violations.push(path)
      ts.forEachChild(node, visit)
    }
    visit(file)
  }
  expect(violations).toEqual([])
})

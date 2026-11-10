// Gestos compartilhados dos testes do editor: botão direito ou alternativa por toque.
export function mapActions(page, mode) {
  const click = async locator => { await locator.scrollIntoViewIfNeeded(); if (mode === 'mobile') await locator.tap(); else await locator.click(); };
  async function background() {
    await page.waitForTimeout(120);
    const position = await page.locator('.map-canvas').evaluate(canvas => {
      const r = canvas.getBoundingClientRect();
      for (const [x, y] of [[.85, .2], [.75, .08], [.4, .18], [.2, .65], [.6, .65]]) {
        const point = { x: r.x + r.width * x, y: r.y + r.height * y };
        const element = document.elementFromPoint(point.x, point.y);
        if (element?.closest('.react-flow__pane') && !element.closest('.react-flow__node, .react-flow__edge, [data-line-part], .map-context, .react-flow__controls, .react-flow__minimap')) return point;
      }
      throw Error('Não foi encontrado fundo livre para abrir o menu.');
    });
    if (mode === 'mobile') {
      await page.touchscreen.tap(position.x, position.y);
      await click(page.getByRole('button', { name: 'Ações do mapa', exact: true }));
    } else await page.mouse.click(position.x, position.y, { button: 'right' });
    await page.getByRole('menu', { name: 'Ações do mapa', exact: true }).waitFor();
  }
  async function item(locator) {
    await locator.scrollIntoViewIfNeeded();
    if (mode === 'mobile') {
      const overlappingControl = await locator.evaluate(element => {
        const r = element.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
        const top = document.elementFromPoint(x, y);
        return element.dataset.lineId && top?.dataset.lineId === element.dataset.lineId ? { x, y } : null;
      });
      // No zoom reduzido, tocar a ponta A/B da própria ligação também a seleciona.
      if (overlappingControl) await page.touchscreen.tap(overlappingControl.x, overlappingControl.y);
      else await locator.tap();
      await page.waitForTimeout(150);
      await click(page.getByRole('button', { name: 'Ações do mapa', exact: true }));
    } else await locator.click({ button: 'right' });
    await page.getByRole('menu', { name: 'Ações do item', exact: true }).waitFor();
  }
  async function choose(name) { await click(page.getByRole('menu').getByRole('menuitem', { name, exact: true })); }
  return { background, item, choose,
    pane: async name => { await background(); await choose(name); },
    on: async (locator, name) => { await item(locator); await choose(name); },
  };
}

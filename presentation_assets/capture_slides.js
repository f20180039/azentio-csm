const puppeteer = require('/Volumes/DiskD/OFFLINEHACK/azentio-csm/frontend/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const ASSETS_DIR = '/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets';

async function capture() {
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1440,900']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });

  // Sign in by setting session
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle0' });
  await page.evaluate(() => {
    sessionStorage.setItem('azentio-csm-session', JSON.stringify({
      username: 'admin',
      password: 'admin',
      roles: ['ADMIN', 'REVIEWER', 'ANALYST']
    }));
  });

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // 1. Support Desk
  console.log('Capturing 1. Support Desk...');
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(ASSETS_DIR, '01_support_desk.png') });

  // 2. Dashboard
  console.log('Capturing 2. Dashboard...');
  await page.goto('http://localhost:5173/dashboard', { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(ASSETS_DIR, '02_dashboard.png') });

  // 3. Multilingual Call Transcript (Kannada + English translations)
  console.log('Capturing 3. Kannada Call...');
  await page.goto('http://localhost:5173/support/calls/475b0ac5-e061-499d-86be-e333435b670a', { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(ASSETS_DIR, '03_kannada_call.png') });

  // 4. Tool Trace & Explainability (expand Retrieved card)
  console.log('Capturing 4. Tool Trace & Explainability...');
  try {
    await page.evaluate(() => {
      const details = document.querySelectorAll('details.sc-retrieved');
      if (details.length > 0) details[0].open = true;
    });
    await sleep(600);
  } catch (e) {}
  await page.screenshot({ path: path.join(ASSETS_DIR, '04_tool_trace.png') });

  // 5. Customer Verification Card
  console.log('Capturing 5. Customer Verification Card...');
  await page.goto('http://localhost:5173/support/calls/475b0ac5-e061-499d-86be-e333435b670a', { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(ASSETS_DIR, '05_customer_verification.png') });

  // 6. Simulator Ops Records (Tickets & Complaints)
  console.log('Capturing 6. Operations Records...');
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle0' });
  await sleep(1500);
  try {
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const ticketsBtn = btns.find(b => b.textContent && b.textContent.includes('Tickets'));
      if (ticketsBtn) ticketsBtn.click();
    });
    await sleep(600);
  } catch (e) {}
  await page.screenshot({ path: path.join(ASSETS_DIR, '06_ops_records.png') });

  // 7. Case Workspace & Hash-Chained Audit Trail
  console.log('Capturing 7. Case Audit Trail...');
  await page.goto('http://localhost:5173/cases/475b0ac5-e061-499d-86be-e333435b670a', { waitUntil: 'networkidle0' });
  await sleep(1500);
  try {
    await page.evaluate(() => {
      const tabs = Array.from(document.querySelectorAll('button[role="tab"]'));
      const auditTab = tabs.find(t => t.textContent && t.textContent.includes('Audit'));
      if (auditTab) auditTab.click();
    });
    await sleep(800);
    // Click verify chain button
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const verifyBtn = btns.find(b => b.textContent && b.textContent.includes('Verify chain'));
      if (verifyBtn) verifyBtn.click();
    });
    await sleep(1000);
  } catch (e) {}
  await page.screenshot({ path: path.join(ASSETS_DIR, '07_audit_chain.png') });

  // 8. Review Queue with Date Filter
  console.log('Capturing 8. Review Queue with Date Filter...');
  await page.goto('http://localhost:5173/queue?datePreset=today', { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(ASSETS_DIR, '08_queue_date_filter.png') });

  // 9. Insights & Quality Review
  console.log('Capturing 9. Support Insights...');
  await page.goto('http://localhost:5173/insights', { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(ASSETS_DIR, '09_insights_analytics.png') });

  // 10. Policy Renewals Queue
  console.log('Capturing 10. Renewals Queue...');
  await page.goto('http://localhost:5173/renewals', { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(ASSETS_DIR, '10_renewals_queue.png') });

  await browser.close();
  console.log('All 10 slides captured successfully!');
}

capture().catch(err => {
  console.error('Error during capture:', err);
  process.exit(1);
});

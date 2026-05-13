import path from "node:path";
import { fileURLToPath } from "node:url";

const STYLE = {
  bg: "#F7F4EC",
  paper: "#FFFDF7",
  ink: "#17202A",
  soft: "#5C6670",
  muted: "#8C8578",
  mist: "#E8E3D6",
  teal: "#1E7A78",
  coral: "#D85C4A",
  gold: "#D99B2B",
  green: "#4C8A43",
  blue: "#3A6EA5",
  plum: "#6D5A8D",
  dark: "#17202A",
  title: "Georgia",
  body: "Avenir Next",
  mono: "Menlo",
};

const TRANSPARENT = "#00000000";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.resolve(HERE, "../assets");

function asset(filename) {
  return path.join(ASSETS, filename);
}

function rect(slide, ctx, x, y, w, h, fill, opts = {}) {
  return ctx.addShape(slide, {
    left: x,
    top: y,
    width: w,
    height: h,
    geometry: opts.geometry ?? "rect",
    fill,
    line: opts.line ?? ctx.line(),
    name: opts.name,
  });
}

function text(slide, ctx, value, x, y, w, h, opts = {}) {
  return ctx.addText(slide, {
    text: String(value ?? ""),
    left: x,
    top: y,
    width: w,
    height: h,
    fontSize: opts.size ?? 18,
    color: opts.color ?? STYLE.ink,
    bold: Boolean(opts.bold),
    typeface: opts.face ?? STYLE.body,
    align: opts.align ?? "left",
    valign: opts.valign ?? "top",
    fill: opts.fill ?? TRANSPARENT,
    line: opts.line ?? ctx.line(),
    insets: opts.insets ?? { left: 0, right: 0, top: 0, bottom: 0 },
    name: opts.name,
  });
}

function bg(slide, ctx, dark = false) {
  rect(slide, ctx, 0, 0, ctx.W, ctx.H, dark ? STYLE.dark : STYLE.bg);
  if (!dark) rect(slide, ctx, 0, 0, ctx.W, 6, STYLE.ink);
}

function rule(slide, ctx, x, y, w, color = STYLE.ink, weight = 1) {
  rect(slide, ctx, x, y, w, weight, color);
}

function vRule(slide, ctx, x, y, h, color = STYLE.ink, weight = 1) {
  rect(slide, ctx, x, y, weight, h, color);
}

function connector(slide, ctx, x1, y, x2, color = STYLE.teal) {
  const width = Math.max(18, x2 - x1);
  rect(slide, ctx, x1, y - 7, width, 14, color, { geometry: "rightArrow" });
}

function kicker(slide, ctx, label, dark = false) {
  rect(slide, ctx, 58, 48, 5, 34, dark ? STYLE.gold : STYLE.coral, { name: "kicker-marker" });
  text(slide, ctx, label.toUpperCase(), 76, 50, 360, 28, {
    size: 10,
    color: dark ? "#F7F4EC" : STYLE.ink,
    bold: true,
    valign: "middle",
    name: "kicker-label",
  });
}

function title(slide, ctx, value, x = 58, y = 92, w = 930, h = 96, size = 34, color = STYLE.ink) {
  return text(slide, ctx, value, x, y, w, h, {
    size,
    color,
    face: STYLE.title,
    bold: true,
    insets: { left: 0, right: 0, top: 0, bottom: 4 },
  });
}

function note(slide, ctx, value, x, y, w, h, opts = {}) {
  return text(slide, ctx, value, x, y, w, h, {
    size: opts.size ?? 12,
    color: opts.color ?? STYLE.soft,
    face: opts.face ?? STYLE.body,
    bold: opts.bold,
    align: opts.align,
    valign: opts.valign,
    fill: opts.fill,
    line: opts.line,
    insets: opts.insets,
  });
}

function footer(slide, ctx, page, source, dark = false) {
  const color = dark ? "#C9D2D8" : STYLE.muted;
  rule(slide, ctx, 58, 665, 1044, dark ? "#4B5560" : STYLE.mist, 1);
  note(slide, ctx, source, 58, 678, 860, 18, { size: 8.5, color });
  note(slide, ctx, String(page).padStart(2, "0"), 1166, 674, 42, 22, {
    size: 12,
    color,
    bold: true,
    align: "right",
  });
}

async function visual(slide, ctx, filename, x, y, w, h, opts = {}) {
  const img = await ctx.addImage(slide, {
    path: asset(filename),
    left: x,
    top: y,
    width: w,
    height: h,
    fit: opts.fit ?? "cover",
    alt: opts.alt ?? "Generated presentation visual",
  });
  if (opts.border) rect(slide, ctx, x, y, w, h, TRANSPARENT, { line: ctx.line(opts.border, 1.2) });
  return img;
}

function chip(slide, ctx, value, x, y, w, fill, color = STYLE.ink) {
  rect(slide, ctx, x, y, w, 30, fill, { line: ctx.line(fill, 1) });
  text(slide, ctx, value, x + 10, y + 6, w - 20, 16, {
    size: 9.5,
    color,
    bold: true,
    align: "center",
    valign: "middle",
  });
}

function metric(slide, ctx, value, label, caption, x, y, accent, dark = false) {
  vRule(slide, ctx, x, y + 2, 68, accent, 3);
  text(slide, ctx, value, x + 16, y, 150, 34, {
    size: 28,
    color: dark ? "#FFFFFF" : STYLE.ink,
    face: STYLE.title,
    bold: true,
  });
  text(slide, ctx, label.toUpperCase(), x + 16, y + 38, 170, 18, {
    size: 8.8,
    color: dark ? "#D6DDE3" : STYLE.soft,
    bold: true,
  });
  note(slide, ctx, caption, x + 16, y + 56, 180, 22, {
    size: 8.5,
    color: dark ? "#AEB9C2" : STYLE.muted,
  });
}

function salesCard(slide, ctx, label, value, body, x, y, w, h, color, opts = {}) {
  rect(slide, ctx, x, y, w, h, opts.fill ?? STYLE.paper, { line: ctx.line(color, 1.4) });
  rect(slide, ctx, x, y, 8, h, color);
  text(slide, ctx, label, x + 24, y + 20, w - 48, 24, { size: 16, color: opts.dark ? "#FFFFFF" : STYLE.ink, bold: true });
  text(slide, ctx, value, x + 24, y + 56, w - 48, 34, {
    size: opts.valueSize ?? 26,
    color: opts.dark ? "#FFFFFF" : STYLE.ink,
    face: STYLE.title,
    bold: true,
  });
  note(slide, ctx, body, x + 24, y + 98, w - 48, h - 116, {
    size: opts.bodySize ?? 10.6,
    color: opts.dark ? "#D7E1E8" : STYLE.soft,
  });
}

function compactCard(slide, ctx, label, value, body, x, y, w, h, color) {
  rect(slide, ctx, x, y, w, h, STYLE.paper, { line: ctx.line(color, 1.4) });
  rect(slide, ctx, x, y, 6, h, color);
  text(slide, ctx, label, x + 18, y + 12, w - 36, 18, { size: 10, color: STYLE.soft, bold: true });
  text(slide, ctx, value, x + 18, y + 34, w - 36, 22, { size: 16, color: STYLE.ink, bold: true });
  note(slide, ctx, body, x + 18, y + 60, w - 36, h - 68, { size: 8.8, color: STYLE.soft });
}

function node(slide, ctx, label, sub, x, y, w, h, color, opts = {}) {
  rect(slide, ctx, x, y, w, h, opts.fill ?? STYLE.paper, {
    line: ctx.line(color, opts.lineWidth ?? 1.2),
  });
  text(slide, ctx, label, x + 16, y + 13, w - 32, 24, {
    size: opts.labelSize ?? 15,
    color: opts.labelColor ?? STYLE.ink,
    bold: true,
    valign: "middle",
  });
  if (sub) {
    text(slide, ctx, sub, x + 16, y + 44, w - 32, h - 62, {
      size: opts.subSize ?? 9.5,
      color: opts.subColor ?? STYLE.soft,
      face: opts.mono ? STYLE.mono : STYLE.body,
    });
  }
}

function miniBar(slide, ctx, label, value, max, x, y, w, color, rightLabel) {
  text(slide, ctx, label, x, y, 182, 18, { size: 10.5, color: STYLE.ink, bold: true });
  rect(slide, ctx, x + 202, y + 5, w, 10, STYLE.mist);
  rect(slide, ctx, x + 202, y + 5, Math.max(6, (w * value) / max), 10, color);
  text(slide, ctx, rightLabel ?? String(value), x + 202 + w + 12, y - 1, 76, 18, {
    size: 10.5,
    color: STYLE.ink,
    bold: true,
  });
}

function wrapped(value, maxChars = 58, maxLines = 3) {
  const words = String(value || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  const lines = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > maxChars && current) {
      lines.push(current);
      current = word;
      if (lines.length >= maxLines - 1) break;
    } else {
      current = next;
    }
  }
  if (current && lines.length < maxLines) lines.push(current);
  return lines.join("\n");
}

export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx, true);
  await visual(slide, ctx, "generated-hero.png", 626, 0, 654, 720, { alt: "Data to capacity decision visual" });
  rect(slide, ctx, 0, 0, 626, 720, "#17202A");
  rect(slide, ctx, 604, 0, 22, 720, "#24313C");
  kicker(slide, ctx, "Produit a vendre", true);
  title(slide, ctx, "Metrics Collector transforme l'infrastructure en decisions capacite.", 58, 108, 520, 210, 42, "#FFFFFF");
  note(
    slide,
    ctx,
    "Une plateforme de pilotage qui collecte l'inventaire, orchestre les metriques et produit des recommandations explicables pour reduire le sur-provisionnement, les risques de saturation et les arbitrages manuels.",
    62,
    332,
    512,
    74,
    { size: 15.2, color: "#D7E1E8" },
  );
  chip(slide, ctx, "Collecter", 62, 438, 92, STYLE.blue, "#FFFFFF");
  chip(slide, ctx, "Orchestrer", 166, 438, 112, STYLE.gold);
  chip(slide, ctx, "Recommander", 290, 438, 132, STYLE.teal, "#FFFFFF");
  chip(slide, ctx, "Gouverner", 434, 438, 112, "#EEF0EA");
  rect(slide, ctx, 58, 532, 548, 108, "#202B35", { line: ctx.line("#3A4650", 1) });
  metric(slide, ctx, "54", "endpoints API", "surface produit admin + operations", 84, 550, STYLE.blue, true);
  metric(slide, ctx, "12", "taches Celery", "collecte et fan-out industrialisables", 314, 550, STYLE.gold, true);
  rule(slide, ctx, 58, 665, 500, "#4B5560", 1);
  note(slide, ctx, "Sources: README, app/api/routes, app/worker/tasks, app/mcp, internal/infra/db/models.py", 58, 678, 500, 18, { size: 8.5, color: "#C9D2D8" });
  note(slide, ctx, "01", 574, 674, 34, 22, { size: 12, color: "#C9D2D8", bold: true, align: "right" });
  return slide;
}

export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx, true);
  kicker(slide, ctx, "Probleme", true);
  title(slide, ctx, "Aujourd'hui, la capacite se decide trop tard, avec trop peu de contexte.", 58, 88, 950, 102, 38, "#FFFFFF");
  note(
    slide,
    ctx,
    "Le produit vend une promesse simple: transformer des donnees techniques dispersees en une decision lisible, tracable et actionnable par les responsables.",
    62,
    198,
    760,
    42,
    { size: 14, color: "#C9D2D8" },
  );
  text(slide, ctx, "3", 76, 278, 116, 138, { size: 112, color: STYLE.coral, face: STYLE.title, bold: true });
  text(slide, ctx, "freins qui coutent du temps, du risque et de la capacite.", 82, 418, 126, 98, {
    size: 15,
    color: "#FFFFFF",
    bold: true,
  });
  salesCard(slide, ctx, "Douleur operationnelle", "Sur-allocation", "Des machines restent dimensionnees par habitude, sans fenetre de metriques consolidee.", 238, 276, 286, 216, STYLE.coral, { fill: "#202B35", dark: true, valueSize: 23 });
  salesCard(slide, ctx, "Risque service", "Saturation", "Les signaux CPU, RAM et disk arrivent dans des outils differents; l'alerte n'arrive pas toujours jusqu'a une decision.", 572, 276, 286, 216, STYLE.gold, { fill: "#202B35", dark: true, valueSize: 23 });
  salesCard(slide, ctx, "Temps manager", "Arbitrage manuel", "Sans recommandation versionnee, chaque decision demande une nouvelle analyse et peu d'historique partage.", 906, 276, 286, 216, STYLE.teal, { fill: "#202B35", dark: true, valueSize: 23 });
  rect(slide, ctx, 82, 548, 1036, 58, "#F7F4EC");
  text(slide, ctx, "Positionnement: une couche de pilotage qui relie inventaire, metriques, recommandations et gouvernance.", 112, 566, 948, 22, {
    size: 14,
    color: STYLE.ink,
    bold: true,
    valign: "middle",
  });
  footer(slide, ctx, 2, "Sources: docs/architecture.md, docs/recommendations.md", true);
  return slide;
}

export async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  kicker(slide, ctx, "Solution");
  title(slide, ctx, "Le control plane relie les donnees techniques a un resultat business.", 58, 88, 980, 86, 35);
  node(slide, ctx, "Connecteurs", "provisioners + providers\nCapsule, Dynatrace, Prometheus, mocks", 78, 246, 232, 118, STYLE.blue, { mono: true });
  node(slide, ctx, "Orchestration", "Beat + Worker + Redis\nfan-out provider / machine", 394, 246, 232, 118, STYLE.gold, { mono: true });
  node(slide, ctx, "Projection produit", "machines, applications,\nmetrics, recommendations", 710, 246, 232, 118, STYLE.green, { mono: true });
  node(slide, ctx, "Decision", "scale_up, scale_down,\nkeep, mixed, unavailable", 1026, 246, 172, 118, STYLE.ink, {
    fill: STYLE.ink,
    labelColor: "#FFFFFF",
    subColor: "#DDE6EA",
    mono: true,
    subSize: 8.6,
  });
  connector(slide, ctx, 322, 305, 382, STYLE.blue);
  connector(slide, ctx, 638, 305, 698, STYLE.gold);
  connector(slide, ctx, 954, 305, 1014, STYLE.green);
  rect(slide, ctx, 88, 440, 1018, 118, STYLE.paper, { line: ctx.line(STYLE.mist, 1) });
  metric(slide, ctx, "6+6", "MCP read-only", "rendre les donnees consommables par assistants et outils", 132, 456, STYLE.teal);
  metric(slide, ctx, "12", "entites DB", "tracer l'inventaire, les metriques et les revisions", 428, 456, STYLE.green);
  metric(slide, ctx, "14", "tests", "base de confiance pour faire evoluer le produit", 724, 456, STYLE.plum);
  footer(slide, ctx, 3, "Sources: docs/architecture.md, app/mcp, internal/infra/db/models.py, tests");
  return slide;
}

export async function slide04(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  await visual(slide, ctx, "generated-workflow.png", 0, 176, 1280, 366, { alt: "Generated data-to-decision workflow visual" });
  rect(slide, ctx, 0, 0, 1280, 190, "rgba(247, 244, 236, 0.96)");
  rect(slide, ctx, 0, 542, 1280, 178, "rgba(247, 244, 236, 0.96)");
  kicker(slide, ctx, "Promesse produit");
  title(slide, ctx, "De l'inventaire aux recommandations, la boucle produit est complete.", 58, 82, 960, 88, 35);
  compactCard(slide, ctx, "1. Voir", "Inventaire", "Machines, applications, environnement, region et flavor courant.", 78, 562, 304, 92, STYLE.blue);
  compactCard(slide, ctx, "2. Mesurer", "Utilisation", "Echantillons CPU, RAM et disk par provider, machine et date.", 488, 562, 304, 92, STYLE.gold);
  compactCard(slide, ctx, "3. Decider", "Recommandation", "Action, status, target capacities et historique de revision.", 898, 562, 304, 92, STYLE.teal);
  footer(slide, ctx, 4, "Sources: docs/architecture.md, docs/celery-task-map.md, docs/recommendations.md");
  return slide;
}

export async function slide05(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  kicker(slide, ctx, "Recommandation");
  title(slide, ctx, "Le moteur est vendable parce qu'il explique pourquoi agir.", 58, 88, 950, 86, 35);
  rect(slide, ctx, 70, 218, 552, 360, STYLE.paper, { line: ctx.line(STYLE.mist, 1) });
  text(slide, ctx, "Regles metier lisibles", 96, 244, 280, 26, { size: 18, bold: true });
  miniBar(slide, ctx, "Objectif d'utilisation", 65, 100, 96, 296, 212, STYLE.teal, "65%");
  miniBar(slide, ctx, "Scale up p95", 85, 100, 96, 338, 212, STYLE.coral, ">=85%");
  miniBar(slide, ctx, "Scale up max", 95, 100, 96, 380, 212, STYLE.coral, ">=95%");
  miniBar(slide, ctx, "Scale down p95", 40, 100, 96, 422, 212, STYLE.green, "<=40%");
  miniBar(slide, ctx, "Scale down max", 60, 100, 96, 464, 212, STYLE.green, "<=60%");
  note(slide, ctx, "CPU et RAM peuvent monter ou descendre. Disk reste conservateur: montee possible, pas de downscale propose.", 96, 520, 414, 34, { size: 11.2 });
  rect(slide, ctx, 674, 218, 472, 360, STYLE.ink);
  text(slide, ctx, "Ce que les responsables achetent", 706, 248, 340, 26, { size: 18, color: "#FFFFFF", bold: true });
  [
    ["Confiance", "status ready / partial / error pour savoir quand croire la recommandation"],
    ["Traçabilite", "revision courante + historique, computed_at et details par scope"],
    ["Action", "scale_up, scale_down, mixed, keep, insufficient_data ou unavailable"],
  ].forEach((item, idx) => {
    const y = 314 + idx * 72;
    text(slide, ctx, item[0], 708, y, 120, 24, { size: 15, color: "#FFFFFF", bold: true });
    note(slide, ctx, item[1], 850, y + 1, 240, 32, { size: 10.4, color: "#D4DEE5" });
    if (idx < 2) rule(slide, ctx, 706, y + 48, 360, "#3A4650", 1);
  });
  footer(slide, ctx, 5, "Sources: docs/recommendations.md, internal/usecases/recommendations.py");
  return slide;
}

export async function slide06(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  kicker(slide, ctx, "Scalabilite");
  title(slide, ctx, "Une collecte lancee une fois, executee partout, suivie de bout en bout.", 58, 88, 980, 92, 35);
  note(
    slide,
    ctx,
    "Pour les responsables, la valeur n'est pas Redis ou Celery: c'est la capacite a industrialiser la mesure sans multiplier les actions manuelles.",
    62,
    190,
    850,
    38,
    { size: 13.2 },
  );
  rect(slide, ctx, 78, 258, 320, 244, STYLE.ink);
  text(slide, ctx, "1 -> N", 112, 300, 220, 68, { size: 52, color: "#FFFFFF", face: STYLE.title, bold: true });
  text(slide, ctx, "UN ORDRE DE COLLECTE", 116, 382, 190, 18, { size: 9, color: "#D7E1E8", bold: true });
  note(slide, ctx, "Le produit transforme une demande de collecte en executions distribuees par provider et par machine.", 116, 414, 224, 46, {
    size: 11,
    color: "#C9D2D8",
  });
  node(slide, ctx, "Declencher", "API ou planning\nune entree unique", 470, 282, 210, 112, STYLE.blue, { mono: true });
  node(slide, ctx, "Distribuer", "worker + broker\nfan-out maitrise", 740, 282, 210, 112, STYLE.gold, { mono: true });
  node(slide, ctx, "Prouver", "statut + historique\ntrace partagee", 1010, 282, 210, 112, STYLE.green, { mono: true });
  connector(slide, ctx, 696, 338, 724, STYLE.blue);
  connector(slide, ctx, 966, 338, 994, STYLE.gold);
  rect(slide, ctx, 470, 452, 750, 116, STYLE.paper, { line: ctx.line(STYLE.mist, 1) });
  metric(slide, ctx, "Ops", "moins de manuel", "declenchement centralise et suivi visible", 504, 466, STYLE.teal);
  metric(slide, ctx, "DB", "audit inclus", "PENDING, STARTED, SUCCESS, FAILURE, RETRY", 742, 466, STYLE.green);
  metric(slide, ctx, "Run", "exploitable", "Flower, Grafana, Prometheus et logs", 980, 466, STYLE.plum);
  footer(slide, ctx, 6, "Sources: docs/celery-task-map.md, internal/infra/queue/task_tracking.py");
  return slide;
}

export async function slide07(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx, true);
  kicker(slide, ctx, "Confiance", true);
  title(slide, ctx, "La confiance est deja construite dans le produit, pas ajoutee apres.", 58, 88, 1000, 102, 38, "#FFFFFF");
  note(
    slide,
    ctx,
    "La presentation peut rassurer sur trois risques que les responsables vont regarder avant de financer un pilote.",
    62,
    202,
    760,
    36,
    { size: 13.2, color: "#C9D2D8" },
  );
  salesCard(slide, ctx, "Risque acces", "OIDC + roles", "Validation issuer, dates et signature; separation user/admin pour garder les mutations sous controle.", 78, 270, 318, 206, STYLE.blue, { fill: "#202B35", dark: true, valueSize: 24 });
  salesCard(slide, ctx, "Risque secrets", "Chiffrement", "Configurations connecteurs protegees par Fernet; en cas de corruption, le produit ferme proprement.", 482, 270, 318, 206, STYLE.green, { fill: "#202B35", dark: true, valueSize: 24 });
  salesCard(slide, ctx, "Risque decision", "Preuves auditables", "Historique des taches, revisions de recommandation et modele DB donnent une trace defendable.", 886, 270, 318, 206, STYLE.gold, { fill: "#202B35", dark: true, valueSize: 24 });
  rect(slide, ctx, 82, 530, 1036, 70, "#F7F4EC");
  text(slide, ctx, "Message a porter: ce n'est pas seulement un collecteur, c'est une plateforme gouvernable que l'on peut ouvrir progressivement.", 112, 552, 940, 20, {
    size: 13,
    color: STYLE.ink,
    bold: true,
    valign: "middle",
  });
  footer(slide, ctx, 7, "Sources: app/api/main.py, internal/infra/auth/oidc.py, internal/infra/security/encryption.py, internal/infra/db/models.py", true);
  return slide;
}

export async function slide08(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  await visual(slide, ctx, "generated-roadmap.png", 0, 190, 1280, 346, { alt: "Generated pilot-to-industrialization roadmap visual" });
  rect(slide, ctx, 0, 0, 1280, 196, "rgba(247, 244, 236, 0.96)");
  rect(slide, ctx, 0, 536, 1280, 184, "rgba(247, 244, 236, 0.96)");
  kicker(slide, ctx, "Go-to-market interne");
  title(slide, ctx, "Pilote: 30 jours pour transformer le produit en decision d'investissement.", 58, 82, 1030, 92, 35);
  compactCard(slide, ctx, "Jours 1-7", "Brancher", "1 plateforme cible, providers reels et donnees exploitables.", 86, 554, 286, 96, STYLE.blue);
  compactCard(slide, ctx, "Jours 8-21", "Comparer", "Recommandations face aux decisions actuelles, avec acknowledgement.", 492, 554, 286, 96, STYLE.green);
  compactCard(slide, ctx, "Jours 22-30", "Decider", "ROI, risques, sponsoring et ordre de rollout industrialisable.", 898, 554, 286, 96, STYLE.gold);
  footer(slide, ctx, 8, "Sources: docs/deployment.md, docker-compose.example.yml");
  return slide;
}

export async function slide09(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx, true);
  kicker(slide, ctx, "Decision", true);
  text(slide, ctx, "PILOTE", 992, 80, 168, 54, { size: 34, color: STYLE.gold, face: STYLE.title, bold: true, align: "right" });
  title(slide, ctx, "La demande aux responsables: financer un pilote court et mesurable.", 58, 92, 760, 146, 40, "#FFFFFF");
  note(
    slide,
    ctx,
    "Le produit est assez avance pour etre vendu en interne: API gouvernee, orchestration asynchrone, recommandations explicables, observabilite et trajectoire de deploiement.",
    62,
    250,
    760,
    48,
    { size: 14.5, color: "#C9D2D8" },
  );
  salesCard(slide, ctx, "Pourquoi maintenant", "Decision capacity", "Chaque cycle de collecte peut devenir une recommandation tracable plutot qu'une analyse ponctuelle.", 82, 300, 304, 178, STYLE.blue, { fill: "#202B35", dark: true, valueSize: 22 });
  salesCard(slide, ctx, "Ce qu'il faut", "Perimetre pilote", "Une plateforme cible, des providers reels, et un sponsor pour valider les actions recommandees.", 488, 300, 304, 178, STYLE.green, { fill: "#202B35", dark: true, valueSize: 22 });
  salesCard(slide, ctx, "Ce qu'on mesure", "Gain + confiance", "Reduction des arbitrages manuels, qualite des recommandations, taux d'acknowledgement.", 894, 300, 304, 178, STYLE.gold, { fill: "#202B35", dark: true, valueSize: 22 });
  rect(slide, ctx, 86, 538, 1010, 56, "#F7F4EC");
  text(slide, ctx, "Arbitrages demandes: choisir le perimetre pilote, confirmer les providers cibles, valider qui peut accuser reception des recommandations.", 112, 557, 940, 20, {
    size: 13,
    color: STYLE.ink,
    bold: true,
    valign: "middle",
  });
  footer(slide, ctx, 9, "Sources: synthese du code et des docs; aucune metrique de production inventee", true);
  return slide;
}

"""
graph_card.py — Visualizzazione interattiva del grafo relazionale Second Brain (D3.js).
Design Apple Glassmorphism, drag & drop fluido, zoom & pan e tracking dinamico
dello stato di sincronizzazione della sessione corrente.
"""
import json
from typing import Optional
import streamlit as st

from src.agent.domain.models import SessionExtractionResult
from src.agent.domain.ports import KnowledgeServicePort
from src.agent.presentation.state import run_async


def render_graph_card(session: SessionExtractionResult, knowledge_service: Optional[KnowledgeServicePort] = None) -> None:
    """Renderizza la card interattiva del Second Brain Knowledge Graph con D3.js."""
    # Recupera il servizio Obsidian se non passato
    ks = knowledge_service or st.session_state.get("knowledge")
    if not ks:
        st.warning("Servizio Second Brain non disponibile.")
        return

    # Estrazione dati grafo (vault su disco + sessione live)
    try:
        graph_data = run_async(ks.get_vault_graph_data(session))
    except Exception as e:
        graph_data = {"nodes": [], "links": []}

    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", [])
    num_nodes = len(nodes)
    num_links = len(links)

    # Identifica il nodo della sessione corrente
    curr_node = next((n for n in nodes if n.get("is_current_session")), None)
    is_synced = curr_node and curr_node.get("sync_status") == "EXECUTED"

    with st.container(border=True):
        # ── HEADER CARD APPLE STYLE ──────────────────────────────────────────
        col_title, col_status = st.columns([2.5, 2])
        with col_title:
            st.markdown(
                """
                <div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">
                    <span style="font-size:22px;">🧠</span>
                    <div>
                        <h3 style="font-size:17.5px; font-weight:700; color:#1A1A1E; margin:0; letter-spacing:-0.02em;">
                            Second Brain Knowledge Graph
                        </h3>
                        <span style="font-size:12px; color:#6E6E73; font-weight:500;">
                """
                f"{num_nodes} Nodi • {num_links} Connessioni Attive"
                """
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col_status:
            status_badge = (
                '<span class="aria-pill aria-pill-green" style="font-size:11px; padding:3px 10px;">🟢 Sincronizzato nel Vault</span>'
                if is_synced else
                '<span class="aria-pill aria-pill-amber" style="font-size:11px; padding:3px 10px;">🟡 In attesa di sync</span>'
            )
            st.markdown(
                f"""
                <div style="text-align:right; display:flex; flex-direction:column; align-items:flex-end; gap:6px;">
                    {status_badge}
                    <div style="display:flex; gap:10px; font-size:11px; font-weight:600;">
                        <span style="color:#007AFF;">● Persone</span>
                        <span style="color:#5856D6;">● Riunioni</span>
                        <span style="color:#34C759;">● Contesto</span>
                        <span style="color:#FF9500;">● Sessione</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # ── CODICE D3.JS INTERATTIVO (FORCE-DIRECTED GRAPH) ───────────────────
        graph_json = json.dumps(graph_data)

        d3_html = f"""
        <!DOCTYPE html>
        <html lang="it">
        <head>
            <meta charset="utf-8">
            <script src="https://d3js.org/d3.v7.min.js"></script>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    background: #FAFAFC;
                    overflow: hidden;
                    user-select: none;
                    -webkit-user-select: none;
                }}
                #graph-container {{
                    width: 100%;
                    height: 410px;
                    position: relative;
                    border: 1px solid #E1E3EB;
                    border-radius: 12px;
                    background: radial-gradient(circle at 50% 50%, #FFFFFF 0%, #F5F6F9 100%);
                    box-shadow: inset 0 1px 3px rgba(0,0,0,0.02);
                }}
                svg {{
                    width: 100%;
                    height: 100%;
                    cursor: grab;
                }}
                svg:active {{
                    cursor: grabbing;
                }}
                .link {{
                    stroke: #D1D5DB;
                    stroke-opacity: 0.65;
                    stroke-width: 1.5px;
                    transition: stroke 0.2s, stroke-opacity 0.2s;
                }}
                .link.highlighted {{
                    stroke: #1A1A1E;
                    stroke-opacity: 0.9;
                    stroke-width: 2.2px;
                }}
                .node circle {{
                    stroke-width: 2px;
                    cursor: pointer;
                    transition: transform 0.2s, filter 0.2s;
                }}
                .node:hover circle {{
                    filter: drop-shadow(0 4px 8px rgba(0,0,0,0.2));
                }}
                .node text {{
                    font-size: 11px;
                    font-weight: 600;
                    fill: #1A1A1E;
                    pointer-events: none;
                    text-anchor: middle;
                    paint-order: stroke;
                    stroke: #FFFFFF;
                    stroke-width: 3.5px;
                    stroke-linecap: round;
                    stroke-linejoin: round;
                }}
                /* Anello pulsante per la sessione non ancora sincronizzata */
                @keyframes pulse-amber {{
                    0% {{ r: 24; stroke-opacity: 0.8; stroke-width: 2.5px; }}
                    50% {{ r: 32; stroke-opacity: 0.15; stroke-width: 6px; }}
                    100% {{ r: 24; stroke-opacity: 0.8; stroke-width: 2.5px; }}
                }}
                .pulse-ring {{
                    animation: pulse-amber 2.2s infinite ease-in-out;
                    fill: none;
                    stroke: #FF9500;
                    pointer-events: none;
                }}
                /* Floating Tooltip macOS Glassmorphism */
                #tooltip {{
                    position: absolute;
                    display: none;
                    pointer-events: none;
                    background: rgba(255, 255, 255, 0.94);
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    border: 1px solid rgba(0, 0, 0, 0.08);
                    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.04);
                    border-radius: 9px;
                    padding: 8px 12px;
                    font-size: 11.5px;
                    color: #1A1A1E;
                    z-index: 1000;
                    max-width: 260px;
                    line-height: 1.4;
                    transform: translate(-50%, -125%);
                    transition: opacity 0.15s ease-out;
                }}
                #tooltip .tt-cat {{
                    font-size: 9.5px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    display: inline-block;
                    margin-bottom: 2px;
                }}
                #tooltip .tt-title {{
                    font-size: 13px;
                    font-weight: 700;
                    color: #1A1A1E;
                    margin-bottom: 2px;
                }}
                #tooltip .tt-desc {{
                    font-size: 11px;
                    color: #555860;
                }}
                /* Toolbar controlli */
                .graph-controls {{
                    position: absolute;
                    bottom: 12px;
                    right: 12px;
                    display: flex;
                    gap: 6px;
                    z-index: 10;
                }}
                .ctrl-btn {{
                    background: rgba(255, 255, 255, 0.9);
                    backdrop-filter: blur(8px);
                    border: 1px solid #D2D6DC;
                    border-radius: 7px;
                    width: 28px;
                    height: 28px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 14px;
                    font-weight: 700;
                    color: #374151;
                    cursor: pointer;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
                    transition: all 0.15s;
                }}
                .ctrl-btn:hover {{
                    background: #FFFFFF;
                    color: #007AFF;
                    border-color: #007AFF;
                }}
            </style>
        </head>
        <body>
            <div id="graph-container">
                <div id="tooltip"></div>
                <div class="graph-controls">
                    <button class="ctrl-btn" id="btn-zoom-in" title="Ingrandisci">+</button>
                    <button class="ctrl-btn" id="btn-zoom-out" title="Riduci">−</button>
                    <button class="ctrl-btn" id="btn-reset" title="Ripristina vista">⟲</button>
                </div>
                <svg id="network-svg"></svg>
            </div>

            <script>
                const data = {graph_json};
                const container = document.getElementById("graph-container");
                const width = container.clientWidth || 700;
                const height = 410;

                const svg = d3.select("#network-svg")
                    .attr("viewBox", [0, 0, width, height]);

                // Layer contenitore per Zoom & Pan
                const g = svg.append("g");

                const zoom = d3.zoom()
                    .scaleExtent([0.4, 3])
                    .on("zoom", (event) => {{
                        g.attr("transform", event.transform);
                    }});

                svg.call(zoom);

                // Forze fisiche calibrate (slanci fluidi e distanziamento perfetto)
                const simulation = d3.forceSimulation(data.nodes)
                    .force("link", d3.forceLink(data.links).id(d => d.id).distance(d => d.distance || 90))
                    .force("charge", d3.forceManyBody().strength(-280))
                    .force("center", d3.forceCenter(width / 2, height / 2))
                    .force("collide", d3.forceCollide().radius(d => (d.val || 12) + 16).iterations(2));

                // Disegno Collegamenti (Links)
                const link = g.append("g")
                    .attr("class", "links")
                    .selectAll("line")
                    .data(data.links)
                    .join("line")
                    .attr("class", "link");

                // Disegno Nodi
                const node = g.append("g")
                    .attr("class", "nodes")
                    .selectAll("g")
                    .data(data.nodes)
                    .join("g")
                    .attr("class", "node")
                    .call(d3.drag()
                        .on("start", dragstarted)
                        .on("drag", dragged)
                        .on("end", dragended));

                // Anello pulsante per la sessione corrente in attesa di sync
                node.filter(d => d.is_current_session && d.sync_status === "PROPOSED")
                    .append("circle")
                    .attr("class", "pulse-ring");

                // Cerchio principale
                node.append("circle")
                    .attr("r", d => d.val || 12)
                    .attr("fill", d => d.color || "#007AFF")
                    .attr("stroke", d => d.is_current_session ? (d.sync_status === "EXECUTED" ? "#34C759" : "#FF9500") : "#FFFFFF")
                    .attr("stroke-width", d => d.is_current_session ? 3.5 : 2);

                // Etichetta testuale leggibile
                node.append("text")
                    .attr("dy", d => (d.val || 12) + 14)
                    .text(d => d.name);

                // ── TOOLTIP GESTURE ──────────────────────────────────────────
                const tooltip = d3.select("#tooltip");

                node.on("mouseover", (event, d) => {{
                    const catLabels = {{
                        "person": "Interlocutore / Contatto",
                        "meeting": "Meeting Vault",
                        "context": "Progetto / Tag",
                        "session": "Sessione Attiva"
                    }};
                    const catColor = d.color || "#007AFF";
                    const catText = catLabels[d.category] || "Second Brain Node";

                    tooltip.html(`
                        <div class="tt-cat" style="color:${{catColor}};">${{catText}}</div>
                        <div class="tt-title">${{d.name}}</div>
                        <div class="tt-desc">${{d.details || ""}}</div>
                    `)
                    .style("display", "block")
                    .style("opacity", 1);

                    // Evidenzia collegamenti adiacenti
                    link.classed("highlighted", l => l.source.id === d.id || l.target.id === d.id);
                }})
                .on("mousemove", (event) => {{
                    const [mx, my] = d3.pointer(event, container);
                    tooltip.style("left", mx + "px").style("top", (my - 12) + "px");
                }})
                .on("mouseout", () => {{
                    tooltip.style("display", "none").style("opacity", 0);
                    link.classed("highlighted", false);
                }});

                // ── SIMULATION TICK ──────────────────────────────────────────
                simulation.on("tick", () => {{
                    link
                        .attr("x1", d => d.source.x)
                        .attr("y1", d => d.source.y)
                        .attr("x2", d => d.target.x)
                        .attr("y2", d => d.target.y);

                    node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
                }});

                function dragstarted(event, d) {{
                    if (!event.active) simulation.alphaTarget(0.3).restart();
                    d.fx = d.x;
                    d.fy = d.y;
                }}

                function dragged(event, d) {{
                    d.fx = event.x;
                    d.fy = event.y;
                }}

                function dragended(event, d) {{
                    if (!event.active) simulation.alphaTarget(0);
                    d.fx = null;
                    d.fy = null;
                }}

                // ── CONTROLLI ZOOM ───────────────────────────────────────────
                document.getElementById("btn-zoom-in").addEventListener("click", () => {{
                    svg.transition().duration(250).call(zoom.scaleBy, 1.3);
                }});
                document.getElementById("btn-zoom-out").addEventListener("click", () => {{
                    svg.transition().duration(250).call(zoom.scaleBy, 0.7);
                }});
                document.getElementById("btn-reset").addEventListener("click", () => {{
                    svg.transition().duration(350).call(zoom.transform, d3.zoomIdentity);
                    simulation.alpha(0.4).restart();
                }});
            </script>
        </body>
        </html>
        """

        st.components.v1.html(d3_html, height=430)

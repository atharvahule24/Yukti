import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { getGraph, getFact } from '../../lib/api'
import type { Node, Link } from '../../lib/api'
import ForceGraph2D from 'react-force-graph-2d'
import type { ForceGraphMethods, LinkObject, NodeObject } from 'react-force-graph-2d'
import { Loader2, Share2, X } from 'lucide-react'

// Extended node type for styling
interface StyledNode extends Node {
  isRoot?: boolean;
  isMainBranch?: boolean;
  isSubNode?: boolean;
  branchColor?: string;
  __bckgDimensions?: [number, number];
  __pill?: { x: number, y: number, r: number } | null;
  x?: number;
  y?: number;
}

type GraphEndpoint = string | number | StyledNode

interface GraphLink extends Omit<Link, 'source' | 'target'> {
  source?: GraphEndpoint;
  target?: GraphEndpoint;
}

type GraphNodeObject = NodeObject<StyledNode>
type GraphLinkObject = LinkObject<StyledNode, GraphLink>
type GraphMethods = ForceGraphMethods<GraphNodeObject, GraphLinkObject>

const endpointId = (endpoint: GraphEndpoint | undefined) => {
  if (endpoint === undefined) return ''
  return typeof endpoint === 'object' ? String(endpoint.id) : String(endpoint)
}

export function KnowledgeGraph({ sessionId }: { sessionId: string }) {
  const [graphData, setGraphData] = useState<{ nodes: Node[], links: Link[] }>({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [fact, setFact] = useState('')
  const [selectedNode, setSelectedNode] = useState<StyledNode | null>(null)
  const fgRef = useRef<GraphMethods | undefined>(undefined)

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    getGraph(sessionId)
      .then(data => {
        setGraphData(data)
        // Automatically expand the root node on load
        if (data.nodes.length > 0) {
           const incomingCount: Record<string, number> = {}
           data.nodes.forEach(n => incomingCount[n.id] = 0)
           ;(data.links as GraphLink[]).forEach(l => {
             const targetId = endpointId(l.target)
             incomingCount[targetId] = (incomingCount[targetId] || 0) + 1
           })
           const root = data.nodes.find(n => incomingCount[n.id] === 0) || data.nodes[0]
           setExpandedNodes(new Set([root.id]))
        }
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [sessionId])

  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())

  const visibleGraphData = useMemo(() => {
    if (!graphData.nodes.length) return { nodes: [], links: [] }

    const visibleNodes = new Set<string>()
    const incomingCount: Record<string, number> = {}
    graphData.nodes.forEach(n => incomingCount[n.id] = 0)
    const graphLinks = graphData.links as GraphLink[]
    graphLinks.forEach(l => {
      const targetId = endpointId(l.target)
      incomingCount[targetId] = (incomingCount[targetId] || 0) + 1
    })

    // roots are nodes with 0 incoming edges
    let roots = graphData.nodes.filter(n => incomingCount[n.id] === 0) as StyledNode[]
    if (roots.length === 0) roots = [graphData.nodes[0] as StyledNode]

    const branchColors = ['#a855f7', '#14b8a6', '#f43f5e', '#ec4899', '#f59e0b', '#3b82f6'];
    
    // Assign properties to nodes directly
    const root = roots[0];
    if (root) {
       root.isRoot = true;
       // find main branches
       const mainLinks = graphLinks.filter(l => endpointId(l.source) === root.id);
       mainLinks.forEach((l, i) => {
          const tId = endpointId(l.target);
          const tNode = graphData.nodes.find(n => n.id === tId) as StyledNode;
          if (tNode) {
             tNode.isMainBranch = true;
             tNode.branchColor = branchColors[i % branchColors.length];
             
             // dfs for sub nodes
             const stack = [tNode];
             while(stack.length > 0) {
               const curr = stack.pop()!;
               const cLinks = graphLinks.filter(cl => endpointId(cl.source) === curr.id);
               cLinks.forEach(cl => {
                 const ctId = endpointId(cl.target);
                 const ctNode = graphData.nodes.find(n => n.id === ctId) as StyledNode;
                 if (ctNode && !ctNode.branchColor) {
                    ctNode.branchColor = tNode.branchColor;
                    ctNode.isSubNode = true;
                    stack.push(ctNode);
                 }
               })
             }
          }
       });
    }

    const queue = [...roots]
    while (queue.length > 0) {
      const node = queue.shift()!
      if (visibleNodes.has(node.id)) continue
      visibleNodes.add(node.id)

      if (expandedNodes.has(node.id)) {
        const childrenLinks = graphLinks.filter(l => {
          const sourceId = endpointId(l.source)
          return sourceId === node.id
        })
        childrenLinks.forEach(l => {
          const targetId = endpointId(l.target)
          const targetNode = graphData.nodes.find(n => n.id === targetId) as StyledNode
          if (targetNode) queue.push(targetNode)
        })
      }
    }

    return {
      nodes: graphData.nodes.filter(n => visibleNodes.has(n.id)) as StyledNode[],
      links: graphLinks.filter(l => {
        const sourceId = endpointId(l.source)
        const targetId = endpointId(l.target)
        return visibleNodes.has(sourceId) && visibleNodes.has(targetId)
      })
    }
  }, [graphData, expandedNodes])

  const handleGenerate = async () => {
    if (!sessionId) return
    setGenerating(true)
    try {
      getFact(sessionId).then(res => setFact(res.fact)).catch(() => {})
      const { generateGraph } = await import('../../lib/api')
      const data = await generateGraph(sessionId)
      setGraphData(data)
    } catch (e) {
      console.error(e)
    } finally {
      setGenerating(false)
    }
  }

  const handleNodeClick = useCallback((node: GraphNodeObject) => {
    if (!fgRef.current) return;

    // Zoom in to node
    fgRef.current.centerAt(node.x, node.y, 1000)
    fgRef.current.zoom(1.5, 2000)
    
    // Toggle expansion
    setExpandedNodes(prev => {
      const nodeId = String(node.id)
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });

    // Set selected node to show detail card
    setSelectedNode(node);
  }, [])

  useEffect(() => {
    if (fgRef.current) {
      // Create repulsion for radial layout
      const chargeForce = fgRef.current.d3Force('charge')
      chargeForce?.strength?.(-800);
      chargeForce?.distanceMax?.(600);
    }
  }, [visibleGraphData]);

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin text-[var(--accent-purple)]" /></div>
  
  if (graphData.nodes.length === 0) {
    if (generating) {
       return (
         <div className="flex flex-col items-center justify-center p-12 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] text-center h-[500px] w-full max-w-sm mx-auto mt-12">
            <Loader2 className="animate-spin text-[var(--accent-purple)] mb-6" size={48} />
            <h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Mapping Concepts...</h3>
            {fact && (
               <div className="max-w-md bg-[var(--accent-purple-dim)] p-4 rounded-[var(--radius-lg)] border border-[var(--accent-purple-border)] mt-4">
                 <p className="text-xs font-bold text-[var(--accent-purple)] uppercase mb-1">Did you know?</p>
                 <p className="text-sm text-[var(--text-primary)] italic">"{fact}"</p>
               </div>
            )}
         </div>
       )
    }

    return (
      <div className="flex flex-col items-center justify-center p-8 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] w-full max-w-sm mx-auto mt-12 h-[500px]">
        <h3 className="text-xl font-bold mb-4 text-[var(--text-primary)]">Knowledge Graph</h3>
        <p className="text-sm text-[var(--text-secondary)] mb-6 text-center">Generate a hierarchical mind map to visualize topics and subtopics from your material.</p>
        <button
          onClick={handleGenerate}
          className="w-full max-w-sm flex items-center justify-center gap-2 bg-[var(--accent-purple)] text-white py-3 rounded-[var(--radius)] font-bold hover:opacity-90 transition-all"
        >
          <Share2 size={18} /> Generate Mind Map
        </button>
      </div>
    )
  }

  return (
    <div className="w-full h-full min-h-[600px] bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] overflow-hidden relative">
       {/* Hierarchy tree overlay instructions */}
       <div className="absolute top-4 left-4 z-10 bg-[var(--bg-elevated)] border border-[var(--border)] p-3 rounded-[var(--radius)] shadow-sm pointer-events-none">
          <p className="text-xs font-medium text-[var(--text-primary)] mb-1 flex items-center gap-2"><Share2 size={12}/> Interactive Mind Map</p>
          <p className="text-[10px] text-[var(--text-secondary)]">Click a node to ask the AI, or use toggles to expand.</p>
       </div>
       
       {/* Detail Card Overlay */}
       {selectedNode && (
         <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-full max-w-sm bg-[var(--bg-elevated)] border border-[var(--border)] rounded-[var(--radius-lg)] p-5 shadow-2xl z-20 flex flex-col gap-3">
           <button 
             onClick={() => setSelectedNode(null)}
             className="absolute top-4 right-4 text-[var(--text-secondary)] hover:text-white"
           >
             <X size={16} />
           </button>
           <h3 className="text-lg font-bold text-white pr-6">{selectedNode.label || selectedNode.id}</h3>
           <p className="text-sm text-[var(--text-secondary)]">Explore this topic or ask the AI to generate a detailed summary based on the knowledge base.</p>
           <button 
             onClick={() => {
                const q = `Can you explain more about ${selectedNode.label || selectedNode.id}?`;
                window.dispatchEvent(new CustomEvent('yukti:ask', { detail: q }));
             }}
             className="text-sm text-[var(--accent-purple)] font-medium hover:underline self-start flex items-center gap-1 mt-1"
           >
             Ask AI about this topic ↗
           </button>
         </div>
       )}
       
       <ForceGraph2D
         ref={fgRef}
         graphData={visibleGraphData}
         nodeLabel={() => ''}
         // Radial layout
         dagMode="radialout"
         dagLevelDistance={180}
         nodeCanvasObject={(node: GraphNodeObject, ctx: CanvasRenderingContext2D, globalScale: number) => {
           const label = node.label || node.id;
           const isRoot = node.isRoot;
           const isMainBranch = node.isMainBranch;
           const branchColor = node.branchColor || '#6b7280';
           
           const fontSize = isRoot ? Math.max(14 / globalScale, 5) : isMainBranch ? Math.max(12 / globalScale, 4) : Math.max(10 / globalScale, 3);
           ctx.font = `${isRoot ? 'bold ' : ''}${fontSize}px Inter, sans-serif`;
           
           const textWidth = ctx.measureText(label).width;
           const paddingX = fontSize * 1.5;
           const paddingY = fontSize * 1.2;
           const bckgDimensions = [textWidth + paddingX, fontSize + paddingY] as [number, number];
         
           const nodeX = node.x ?? 0;
           const nodeY = node.y ?? 0;
           const x = nodeX - bckgDimensions[0] / 2;
           const y = nodeY - bckgDimensions[1] / 2;
           const w = bckgDimensions[0];
           const h = bckgDimensions[1];
           const r = h / 2; // Full rounded pill
           
           ctx.beginPath();
           ctx.moveTo(x + r, y);
           ctx.lineTo(x + w - r, y);
           ctx.quadraticCurveTo(x + w, y, x + w, y + r);
           ctx.lineTo(x + w, y + h - r);
           ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
           ctx.lineTo(x + r, y + h);
           ctx.quadraticCurveTo(x, y + h, x, y + h - r);
           ctx.lineTo(x, y + r);
           ctx.quadraticCurveTo(x, y, x + r, y);
           ctx.closePath();
           
           if (isRoot) {
             ctx.fillStyle = '#2f3136'; 
             ctx.fill();
             ctx.strokeStyle = '#7c3aed'; 
             ctx.lineWidth = 2 / globalScale;
             ctx.stroke();
           } else if (isMainBranch) {
             ctx.fillStyle = branchColor + '20'; 
             ctx.fill();
             ctx.strokeStyle = branchColor;
             ctx.lineWidth = 1.5 / globalScale;
             ctx.stroke();
           } else {
             ctx.fillStyle = '#131314'; // Match background
             ctx.fill();
             ctx.strokeStyle = branchColor + '60'; 
             ctx.lineWidth = 1 / globalScale;
             ctx.stroke();
           }
         
           // Draw text
           ctx.textAlign = 'center';
           ctx.textBaseline = 'middle';
           ctx.fillStyle = isRoot ? '#ffffff' : isMainBranch ? branchColor : branchColor + 'dd';
           ctx.fillText(String(label), nodeX, nodeY);
         
           node.__bckgDimensions = bckgDimensions;
         }}
         nodePointerAreaPaint={(node: GraphNodeObject, color: string, ctx: CanvasRenderingContext2D) => {
           ctx.fillStyle = color;
           if (node.__bckgDimensions) {
             const nodeX = node.x ?? 0;
             const nodeY = node.y ?? 0;
             ctx.fillRect(nodeX - node.__bckgDimensions[0] / 2, nodeY - node.__bckgDimensions[1] / 2, node.__bckgDimensions[0], node.__bckgDimensions[1]);
           }
         }}
         linkCanvasObject={(link: GraphLinkObject, ctx: CanvasRenderingContext2D, scale: number) => {
           const start = link.source;
           const end = link.target;
           if (typeof start !== 'object' || typeof end !== 'object') return;
           const startX = start.x ?? 0;
           const startY = start.y ?? 0;
           const endX = end.x ?? 0;
           const endY = end.y ?? 0;
           
           const linkColor = end.branchColor ? end.branchColor + '60' : 'rgba(255,255,255,0.15)';
           
           ctx.beginPath();
           ctx.moveTo(startX, startY);
           
           // Slight quadratic curve for radial effect
           const dx = endX - startX;
           const dy = endY - startY;
           const cpX = startX + dx / 2 - dy * 0.15;
           const cpY = startY + dy / 2 + dx * 0.15;
           ctx.quadraticCurveTo(cpX, cpY, endX, endY);
           
           ctx.strokeStyle = linkColor;
           ctx.lineWidth = 1.2 / scale;
           ctx.stroke();
         }}
         backgroundColor="#131314" // Deep dark background
         onNodeClick={handleNodeClick}
         d3VelocityDecay={0.8} // Stop bouncing faster
         cooldownTicks={100} // Settle layout quickly
       />
    </div>
  )
}

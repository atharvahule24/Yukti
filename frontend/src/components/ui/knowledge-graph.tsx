import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { getGraph, generateGraph, getFact, getTaskStatus, TaskTerminalError, isTransientNetworkError } from '../../lib/api'
import type { Node, Link } from '../../lib/api'
import ForceGraph2D from 'react-force-graph-2d'
import type { ForceGraphMethods, LinkObject, NodeObject } from 'react-force-graph-2d'
import { Loader2, Share2, X, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'

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
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const isMountedRef = useRef(true)
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
           setExpandedNodes(new Set(data.nodes.map(n => n.id)))
        }
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [sessionId])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())

  const visibleGraphData = useMemo(() => {
    if (!graphData.nodes.length) return { nodes: [], links: [] }

    const styledNodes: StyledNode[] = graphData.nodes.map(n => ({ ...n }))
    const nodeMap = new Map<string, StyledNode>(styledNodes.map(n => [n.id, n]))
    const graphLinks = graphData.links as GraphLink[]

    const visibleNodes = new Set<string>()
    const incomingCount: Record<string, number> = {}
    styledNodes.forEach(n => incomingCount[n.id] = 0)
    graphLinks.forEach(l => {
      const targetId = endpointId(l.target)
      incomingCount[targetId] = (incomingCount[targetId] || 0) + 1
    })

    // roots are nodes with 0 incoming edges
    let roots = styledNodes.filter(n => incomingCount[n.id] === 0)
    if (roots.length === 0 && styledNodes.length > 0) {
      roots = [styledNodes[0]]
    }

    // Ensure every disconnected component (including cyclic components without 0-incoming nodes) has a root
    const reachedFromRoots = new Set<string>()
    const reachQueue = roots.map(r => r.id)
    reachQueue.forEach(id => reachedFromRoots.add(id))
    while (reachQueue.length > 0) {
      const currId = reachQueue.shift()!
      graphLinks.forEach(l => {
        const s = endpointId(l.source)
        const t = endpointId(l.target)
        if (s === currId && !reachedFromRoots.has(t)) {
          reachedFromRoots.add(t)
          reachQueue.push(t)
        } else if (t === currId && !reachedFromRoots.has(s)) {
          reachedFromRoots.add(s)
          reachQueue.push(s)
        }
      })
    }

    // Any remaining nodes belong to disconnected cycles/components without 0-incoming roots
    styledNodes.forEach(n => {
      if (!reachedFromRoots.has(n.id)) {
        roots.push(n)
        reachedFromRoots.add(n.id)
        reachQueue.push(n.id)
        while (reachQueue.length > 0) {
          const currId = reachQueue.shift()!
          graphLinks.forEach(l => {
            const s = endpointId(l.source)
            const t = endpointId(l.target)
            if (s === currId && !reachedFromRoots.has(t)) {
              reachedFromRoots.add(t)
              reachQueue.push(t)
            } else if (t === currId && !reachedFromRoots.has(s)) {
              reachedFromRoots.add(s)
              reachQueue.push(s)
            }
          })
        }
      }
    })

    const branchColors = ['#a855f7', '#14b8a6', '#f43f5e', '#ec4899', '#f59e0b', '#3b82f6']
    let colorIdx = 0

    // Mark the primary root
    const primaryRoot = roots[0]
    if (primaryRoot) {
      primaryRoot.isRoot = true
    }

    // Assign branch colors across roots and their sub-trees with cycle safety
    roots.forEach((rt, rIdx) => {
      if (rIdx > 0 && !rt.branchColor) {
        rt.branchColor = branchColors[colorIdx++ % branchColors.length]
        rt.isMainBranch = true
      }

      const mainLinks = graphLinks.filter(l => endpointId(l.source) === rt.id || endpointId(l.target) === rt.id)
      mainLinks.forEach(l => {
        const neighborId = endpointId(l.source) === rt.id ? endpointId(l.target) : endpointId(l.source)
        const neighborNode = nodeMap.get(neighborId)
        if (neighborNode && !neighborNode.isRoot && !neighborNode.branchColor) {
          neighborNode.isMainBranch = true
          neighborNode.branchColor = branchColors[colorIdx++ % branchColors.length]

          // Cycle-safe DFS for sub nodes
          const visitedSubNodes = new Set<string>([rt.id, neighborNode.id])
          const stack = [neighborNode]
          while (stack.length > 0) {
            const curr = stack.pop()!
            const cLinks = graphLinks.filter(cl => endpointId(cl.source) === curr.id || endpointId(cl.target) === curr.id)
            cLinks.forEach(cl => {
              const ctId = endpointId(cl.source) === curr.id ? endpointId(cl.target) : endpointId(cl.source)
              if (!visitedSubNodes.has(ctId)) {
                visitedSubNodes.add(ctId)
                const ctNode = nodeMap.get(ctId)
                if (ctNode && !ctNode.isRoot) {
                  if (!ctNode.branchColor) {
                    ctNode.branchColor = neighborNode.branchColor
                    ctNode.isSubNode = true
                  }
                  stack.push(ctNode)
                }
              }
            })
          }
        }
      })
    })

    // Cycle-safe BFS traversal for visibility
    const queue: StyledNode[] = []
    const enqueued = new Set<string>()

    roots.forEach(r => {
      queue.push(r)
      enqueued.add(r.id)
    })

    while (queue.length > 0) {
      const node = queue.shift()!
      visibleNodes.add(node.id)

      if (expandedNodes.has(node.id)) {
        const neighborLinks = graphLinks.filter(l => {
          return endpointId(l.source) === node.id || endpointId(l.target) === node.id
        })
        neighborLinks.forEach(l => {
          const neighborId = endpointId(l.source) === node.id ? endpointId(l.target) : endpointId(l.source)
          if (!enqueued.has(neighborId)) {
            const neighborNode = nodeMap.get(neighborId)
            if (neighborNode) {
              enqueued.add(neighborId)
              queue.push(neighborNode)
            }
          }
        })
      }
    }

    // Ensure all expanded nodes are visible even if disconnected
    styledNodes.forEach(n => {
      if (expandedNodes.has(n.id)) {
        visibleNodes.add(n.id)
      }
    })

    return {
      nodes: styledNodes.filter(n => visibleNodes.has(n.id)),
      links: graphLinks.filter(l => {
        const sourceId = endpointId(l.source)
        const targetId = endpointId(l.target)
        return visibleNodes.has(sourceId) && visibleNodes.has(targetId)
      })
    }
  }, [graphData, expandedNodes])

  const handleGenerate = async (force = false) => {
    if (!sessionId || generating) return
    setGenerating(true)
    setErrorMessage(null)
    try {
      getFact(sessionId).then(res => {
        if (isMountedRef.current) setFact(res.fact)
      }).catch(() => {})
      const task = await generateGraph(sessionId, force) as any
      
      let attempts = 0
      const maxAttempts = 60
      let consecutiveErrors = 0
      const maxConsecutiveErrors = 3
      
      if (task.task_id) {
        while (attempts < maxAttempts) {
          try {
            const status = await getTaskStatus(task.task_id)
            consecutiveErrors = 0
            if (status.state === 'SUCCESS' || status.state === 'success') {
              const data = await getGraph(sessionId)
              if (data.nodes.length > 0 && isMountedRef.current) {
                setExpandedNodes(new Set(data.nodes.map(n => n.id)))
              }
              if (isMountedRef.current) setGraphData(data)
              fgRef.current?.zoomToFit(400)
              break
            }
            if (status.state === 'FAILURE' || status.state === 'failure' || status.state === 'REVOKED' || status.state === 'revoked') {
              throw new TaskTerminalError(status.error || "Generation failed")
            }
          } catch (pollErr: unknown) {
            if (pollErr instanceof TaskTerminalError || !isTransientNetworkError(pollErr)) {
              throw pollErr
            }
            consecutiveErrors++
            if (consecutiveErrors >= maxConsecutiveErrors) {
              throw new Error("Server connection interrupted. Please try again.")
            }
            await new Promise(r => setTimeout(r, 1000))
          }
          await new Promise(r => setTimeout(r, 2000))
          attempts++
        }
        if (attempts >= maxAttempts) {
          throw new Error('Mind Map generation timed out. Please try again.')
        }
      } else {
        if (task.nodes && task.nodes.length > 0 && isMountedRef.current) {
          setExpandedNodes(new Set(task.nodes.map((n: any) => n.id)))
        }
        if (isMountedRef.current) setGraphData(task)
        fgRef.current?.zoomToFit(400)
      }
    } catch (e: any) {
      console.error(e)
      let message = e?.message || 'Mind Map generation failed. Please try again.'
      if (isTransientNetworkError(e) || message === 'Failed to fetch' || e?.name === 'TypeError') {
        message = 'The server is temporarily busy or connection was interrupted. Please wait a moment and try again.'
      }
      toast.error(message)
      if (isMountedRef.current) setErrorMessage(message)
    } finally {
      if (isMountedRef.current) setGenerating(false)
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
  
  const isDegenerate = graphData.nodes.length === 0 || (graphData.nodes.length <= 1 && (!graphData.links || graphData.links.length === 0))

  if (isDegenerate) {
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
        {errorMessage && (
          <div className="w-full max-w-sm mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-[var(--radius)] flex items-start gap-2 text-left">
            <AlertCircle className="text-red-400 shrink-0 mt-0.5" size={16} />
            <p className="text-xs text-red-200">{errorMessage}</p>
          </div>
        )}
        <button
          onClick={() => handleGenerate(true)}
          disabled={generating}
          className="w-full max-w-sm flex items-center justify-center gap-2 bg-[var(--accent-purple)] text-white py-3 rounded-[var(--radius)] font-bold hover:opacity-90 transition-all disabled:opacity-50 cursor-pointer"
        >
          <Share2 size={18} /> Generate Mind Map
        </button>
      </div>
    )
  }

  return (
    <div className="w-full h-full min-h-[600px] bg-[var(--bg-surface)] border border-[var(--border)] rounded-[var(--radius-lg)] overflow-hidden relative">
       {/* Hierarchy tree overlay instructions */}
       <div className="absolute top-4 left-4 z-10 bg-[var(--bg-elevated)] border border-[var(--border)] p-3 rounded-[var(--radius)] shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <p className="text-xs font-medium text-[var(--text-primary)] flex items-center gap-2"><Share2 size={12}/> Interactive Mind Map</p>
            <button
              onClick={() => handleGenerate(true)}
              disabled={generating}
              className="text-[11px] font-medium text-[var(--accent-purple)] hover:underline flex items-center gap-1 cursor-pointer disabled:opacity-50"
            >
              {generating ? <Loader2 size={12} className="animate-spin" /> : null}
              {generating ? 'Regenerating...' : 'Regenerate'}
            </button>
          </div>
          <p className="text-[10px] text-[var(--text-secondary)] mt-1">Click a node to ask the AI, or use toggles to expand.</p>
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
         onEngineStop={() => fgRef.current?.zoomToFit(400, 50)}
       />
    </div>
  )
}

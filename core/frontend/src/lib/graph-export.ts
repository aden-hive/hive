/**
 * Graph export utilities for AgentGraph component.
 * Handles exporting graph as PNG and SVG.
 */

/**
 * Export SVG element as PNG using html2canvas
 * @param svgElement - The SVG element to export
 * @param filename - Name of the output file (without extension)
 */
export async function exportAsPNG(svgElement: SVGElement, filename: string): Promise<void> {
  try {
    // Dynamically import html2canvas to avoid bundling it if not needed
    const html2canvas = (await import("html2canvas")).default;
    
    // Create a canvas from the SVG
    const canvas = await html2canvas(svgElement, {
      scale: 2, // Higher resolution
      backgroundColor: null, // Transparent background
      logging: false,
      useCORS: true,
    });
    
    // Create download link
    const link = document.createElement("a");
    link.download = `${filename}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  } catch (error) {
    console.error("Failed to export as PNG:", error);
    throw new Error(`Failed to export graph as PNG: ${error}`);
  }
}

/**
 * Export SVG element as SVG file
 * @param svgElement - The SVG element to export
 * @param filename - Name of the output file (without extension)
 */
export function exportAsSVG(svgElement: SVGElement, filename: string): void {
  try {
    // Clone the SVG to avoid modifying the original
    const clonedSvg = svgElement.cloneNode(true) as SVGElement;
    
    // Ensure the SVG has proper namespace
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clonedSvg.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
    
    // Add a style element to preserve colors
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = `
      text { font-family: 'Inter', system-ui, sans-serif; }
      .node-label { font-weight: 500; }
      .trigger-label { fill: hsl(210,30%,65%); }
    `;
    clonedSvg.insertBefore(style, clonedSvg.firstChild);
    
    // Serialize to string
    const serializer = new XMLSerializer();
    let source = serializer.serializeToString(clonedSvg);
    
    // Add XML declaration
    source = '<?xml version="1.0" standalone="no"?>\r\n' + source;
    
    // Create data URL and download
    const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(source);
    const link = document.createElement("a");
    link.download = `${filename}.svg`;
    link.href = url;
    link.click();
  } catch (error) {
    console.error("Failed to export as SVG:", error);
    throw new Error(`Failed to export graph as SVG: ${error}`);
  }
}

/**
 * Export graph with current view (respects zoom/pan)
 * @param svgElement - The SVG element to export
 * @param format - Export format ('png' or 'svg')
 * @param filename - Base filename (timestamp will be appended)
 */
export async function exportGraph(
  svgElement: SVGElement,
  format: "png" | "svg",
  filename: string = "graph"
): Promise<void> {
  const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, "-");
  const fullFilename = `${filename}_${timestamp}`;
  
  if (format === "png") {
    await exportAsPNG(svgElement, fullFilename);
  } else {
    exportAsSVG(svgElement, fullFilename);
  }
}

/**
 * Get graph as data URL (for embedding or sharing)
 * @param svgElement - The SVG element to convert
 * @param format - Output format ('png' or 'svg')
 * @returns Promise resolving to data URL string
 */
export async function getGraphDataURL(
  svgElement: SVGElement,
  format: "png" | "svg" = "png"
): Promise<string> {
  if (format === "png") {
    const html2canvas = (await import("html2canvas")).default;
    const canvas = await html2canvas(svgElement, {
      scale: 2,
      backgroundColor: null,
      logging: false,
    });
    return canvas.toDataURL("image/png");
  } else {
    const clonedSvg = svgElement.cloneNode(true) as SVGElement;
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(clonedSvg);
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(source);
  }
}
/**
 * Graph export utilities for AgentGraph component.
 * Handles exporting graph as PNG and SVG.
 */

/**
 * Export SVG element as PNG using html2canvas
 * @param svgElement - The SVG element to export
 * @param filename - Name of the output file (with or without extension)
 * @returns Promise that resolves when export is complete
 */
export async function exportAsPNG(svgElement: SVGElement, filename: string): Promise<void> {
  return new Promise(async (resolve, reject) => {
    try {
      // Ensure filename has .png extension
      const finalFilename = filename.endsWith('.png') ? filename : `${filename}.png`;
      
      // Dynamically import html2canvas to avoid bundling it if not needed
      const html2canvas = (await import("html2canvas")).default;
      
      // Create a wrapper div to contain the SVG (html2canvas works better with HTMLElement)
      const wrapper = document.createElement('div');
      const clonedSvg = svgElement.cloneNode(true) as SVGElement;
      
      // Preserve the viewBox and dimensions
      const viewBox = svgElement.getAttribute('viewBox');
      const width = svgElement.getAttribute('width');
      const height = svgElement.getAttribute('height');
      if (viewBox) clonedSvg.setAttribute('viewBox', viewBox);
      if (width) clonedSvg.setAttribute('width', width);
      if (height) clonedSvg.setAttribute('height', height);
      
      // Apply current transform if present
      const transform = (svgElement as SVGSVGElement).style?.transform;
      if (transform) {
        clonedSvg.style.transform = transform;
      }
      
      wrapper.appendChild(clonedSvg);
      wrapper.style.position = 'absolute';
      wrapper.style.top = '-9999px';
      wrapper.style.left = '-9999px';
      wrapper.style.width = width || 'auto';
      wrapper.style.height = height || 'auto';
      document.body.appendChild(wrapper);
      
      // Create canvas from the wrapper
      const canvas = await html2canvas(wrapper, {
        scale: 2, // Higher resolution
        backgroundColor: null, // Transparent background
        logging: false,
        useCORS: true,
        allowTaint: false,
      });
      
      // Clean up wrapper
      document.body.removeChild(wrapper);
      
      // Create download link
      const link = document.createElement("a");
      link.download = finalFilename;
      link.href = canvas.toDataURL("image/png");
      link.click();
      
      resolve();
    } catch (error) {
      console.error("Failed to export as PNG:", error);
      reject(new Error(`Failed to export graph as PNG: ${error}`));
    }
  });
}

/**
 * Export SVG element as SVG file
 * @param svgElement - The SVG element to export
 * @param filename - Name of the output file (with or without extension)
 */
export function exportAsSVG(svgElement: SVGElement, filename: string): void {
  try {
    // Ensure filename has .svg extension
    const finalFilename = filename.endsWith('.svg') ? filename : `${filename}.svg`;
    
    // Clone the SVG to avoid modifying the original
    const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement;
    
    // Preserve the current transform if present
    const transform = (svgElement as SVGSVGElement).style?.transform;
    if (transform) {
      clonedSvg.style.transform = transform;
    }
    
    // Ensure the SVG has proper namespace
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clonedSvg.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
    
    // Preserve viewBox and dimensions
    const viewBox = svgElement.getAttribute('viewBox');
    const width = svgElement.getAttribute('width');
    const height = svgElement.getAttribute('height');
    if (viewBox) clonedSvg.setAttribute('viewBox', viewBox);
    if (width) clonedSvg.setAttribute('width', width);
    if (height) clonedSvg.setAttribute('height', height);
    
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
    link.download = finalFilename;
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
 * @param filename - Base filename (timestamp will be appended if not already present)
 */
export async function exportGraph(
  svgElement: SVGElement,
  format: "png" | "svg",
  filename: string = "graph"
): Promise<void> {
  // Only add timestamp if the filename doesn't already have one
  // (callers might already include timestamp)
  const hasTimestamp = /_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}/.test(filename);
  const finalFilename = hasTimestamp ? filename : `${filename}_${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}`;
  
  if (format === "png") {
    await exportAsPNG(svgElement, finalFilename);
  } else {
    exportAsSVG(svgElement, finalFilename);
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
    // Dynamically import html2canvas
    const html2canvas = (await import("html2canvas")).default;
    
    // Create wrapper div for html2canvas compatibility
    const wrapper = document.createElement('div');
    const clonedSvg = svgElement.cloneNode(true) as SVGElement;
    wrapper.appendChild(clonedSvg);
    wrapper.style.position = 'absolute';
    wrapper.style.top = '-9999px';
    wrapper.style.left = '-9999px';
    document.body.appendChild(wrapper);
    
    try {
      const canvas = await html2canvas(wrapper, {
        scale: 2,
        backgroundColor: null,
        logging: false,
      });
      return canvas.toDataURL("image/png");
    } finally {
      document.body.removeChild(wrapper);
    }
  } else {
    // SVG format
    const clonedSvg = svgElement.cloneNode(true) as SVGElement;
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clonedSvg.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
    
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(clonedSvg);
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(source);
  }
}

/**
 * Get graph as blob (useful for upload or sharing)
 * @param svgElement - The SVG element to convert
 * @param format - Output format ('png' or 'svg')
 * @returns Promise resolving to Blob
 */
export async function getGraphBlob(
  svgElement: SVGElement,
  format: "png" | "svg" = "png"
): Promise<Blob> {
  if (format === "png") {
    const dataUrl = await getGraphDataURL(svgElement, "png");
    const response = await fetch(dataUrl);
    return await response.blob();
  } else {
    const clonedSvg = svgElement.cloneNode(true) as SVGElement;
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(clonedSvg);
    return new Blob([source], { type: "image/svg+xml" });
  }
}

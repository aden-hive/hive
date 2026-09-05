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
  
  try {
    // Create canvas from the wrapper
    const canvas = await html2canvas(wrapper, {
      scale: 2, // Higher resolution
      backgroundColor: null, // Transparent background
      logging: false,
      useCORS: true,
      allowTaint: false,
    });
    
    // Create download link
    const link = document.createElement("a");
    link.download = finalFilename;
    link.href = canvas.toDataURL("image/png");
    link.click();
  } finally {
    // Always clean up wrapper, even if html2canvas throws
    document.body.removeChild(wrapper);
  }
}

/**
 * Export SVG element as SVG file
 * @param svgElement - The SVG element to export
 * @param filename - Name of the output file (with or without extension)
 */
export function exportAsSVG(svgElement: SVGElement, filename: string): void {
  // Ensure filename has .svg extension
  const finalFilename = filename.endsWith('.svg') ? filename : `${filename}.svg`;
  
  // Clone the SVG to avoid modifying the original
  const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement;
  
  // Preserve the current transform if present
  const transform = (svgElement as SVGSVGElement).style?.transform;
  if (transform) {
    clonedSvg.style.transform = transform;
  }
  
  // Preserve viewBox and dimensions
  const viewBox = svgElement.getAttribute('viewBox');
  const width = svgElement.getAttribute('width');
  const height = svgElement.getAttribute('height');
  if (viewBox) clonedSvg.setAttribute('viewBox', viewBox);
  if (width) clonedSvg.setAttribute('width', width);
  if (height) clonedSvg.setAttribute('height', height);
  
  // Ensure the SVG has proper namespaces
  clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clonedSvg.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  
  // Extract existing styles from the SVG or compute from elements
  // Instead of hardcoding class names, we preserve whatever styles are already present
  // and add minimal base styles to ensure text rendering
  const existingStyle = clonedSvg.querySelector('style');
  if (!existingStyle) {
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    // Use generic selectors that match typical SVG text elements
    // This preserves text rendering without hardcoding specific class names
    style.textContent = `
      text {
        font-family: 'Inter', system-ui, sans-serif;
        dominant-baseline: middle;
      }
    `;
    clonedSvg.insertBefore(style, clonedSvg.firstChild);
  }
  
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
    
    // Preserve viewBox and dimensions (consistent with exportAsPNG)
    const viewBox = svgElement.getAttribute('viewBox');
    const width = svgElement.getAttribute('width');
    const height = svgElement.getAttribute('height');
    if (viewBox) clonedSvg.setAttribute('viewBox', viewBox);
    if (width) clonedSvg.setAttribute('width', width);
    if (height) clonedSvg.setAttribute('height', height);
    
    wrapper.appendChild(clonedSvg);
    wrapper.style.position = 'absolute';
    wrapper.style.top = '-9999px';
    wrapper.style.left = '-9999px';
    wrapper.style.width = width || 'auto';
    wrapper.style.height = height || 'auto';
    document.body.appendChild(wrapper);
    
    try {
      const canvas = await html2canvas(wrapper, {
        scale: 2,
        backgroundColor: null,
        logging: false,
        useCORS: true,
      });
      return canvas.toDataURL("image/png");
    } finally {
      document.body.removeChild(wrapper);
    }
  } else {
    // SVG format
    const clonedSvg = svgElement.cloneNode(true) as SVGElement;
    
    // Preserve viewBox and dimensions
    const viewBox = svgElement.getAttribute('viewBox');
    const width = svgElement.getAttribute('width');
    const height = svgElement.getAttribute('height');
    if (viewBox) clonedSvg.setAttribute('viewBox', viewBox);
    if (width) clonedSvg.setAttribute('width', width);
    if (height) clonedSvg.setAttribute('height', height);
    
    // Set namespaces
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
    
    // Preserve viewBox and dimensions
    const viewBox = svgElement.getAttribute('viewBox');
    const width = svgElement.getAttribute('width');
    const height = svgElement.getAttribute('height');
    if (viewBox) clonedSvg.setAttribute('viewBox', viewBox);
    if (width) clonedSvg.setAttribute('width', width);
    if (height) clonedSvg.setAttribute('height', height);
    
    // Set namespaces
    clonedSvg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clonedSvg.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
    
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(clonedSvg);
    return new Blob([source], { type: "image/svg+xml" });
  }
}

/**
 * Figma API Exploration and Study
 * Understanding capabilities, limits, and data structures
 */

const axios = require('axios');
const fs = require('fs').promises;

class FigmaAPIStudy {
  constructor() {
    this.baseURL = 'https://api.figma.com/v1';
    this.headers = {
      'X-Figma-Token': process.env.FIGMA_ACCESS_TOKEN
    };
    
    // Rate limit tracking
    this.rateLimit = {
      remaining: null,
      reset: null,
      limit: 3000
    };
  }

  /**
   * Available Endpoints Documentation
   */
  endpoints = {
    // Files
    'GET /files/:key': 'Get file content and metadata',
    'GET /files/:key/nodes': 'Get specific nodes from file',
    'GET /files/:key/images': 'Export images from file',
    'GET /files/:key/versions': 'Get file version history',
    'GET /files/:key/comments': 'Get file comments',
    
    // Teams & Projects
    'GET /teams/:team_id/projects': 'List team projects',
    'GET /projects/:project_id/files': 'List project files',
    
    // Styles & Components
    'GET /files/:key/styles': 'Get local styles',
    'GET /files/:key/components': 'Get local components',
    'GET /teams/:team_id/styles': 'Get team styles',
    'GET /teams/:team_id/components': 'Get team components',
    
    // Webhooks
    'POST /webhooks': 'Create webhook subscription',
    'DELETE /webhooks/:id': 'Delete webhook',
    'GET /webhooks/:id/requests': 'Get webhook requests'
  };

  /**
   * Data Structures Available
   */
  dataStructures = {
    Node: {
      id: 'string',
      name: 'string',
      type: 'DOCUMENT | PAGE | FRAME | COMPONENT | TEXT | etc',
      children: 'Node[]',
      visible: 'boolean',
      locked: 'boolean',
      styles: 'StyleMap',
      effects: 'Effect[]',
      constraints: 'Constraints',
      layoutMode: 'NONE | HORIZONTAL | VERTICAL',
      primaryAxisSizingMode: 'FIXED | AUTO',
      counterAxisSizingMode: 'FIXED | AUTO',
      primaryAxisAlignItems: 'MIN | CENTER | MAX | SPACE_BETWEEN | BASELINE',
      counterAxisAlignItems: 'MIN | CENTER | MAX | BASELINE',
      paddingLeft: 'number',
      paddingRight: 'number',
      paddingTop: 'number',
      paddingBottom: 'number',
      itemSpacing: 'number',
      fills: 'Paint[]',
      strokes: 'Paint[]',
      strokeWeight: 'number',
      strokeAlign: 'INSIDE | OUTSIDE | CENTER',
      cornerRadius: 'number',
      rectangleCornerRadii: '[number, number, number, number]'
    },
    
    Paint: {
      type: 'SOLID | GRADIENT_LINEAR | GRADIENT_RADIAL | IMAGE | etc',
      visible: 'boolean',
      opacity: 'number',
      color: 'Color',
      gradientStops: 'ColorStop[]',
      imageRef: 'string'
    },
    
    TextStyle: {
      fontFamily: 'string',
      fontPostScriptName: 'string',
      fontWeight: 'number',
      fontSize: 'number',
      textAlignHorizontal: 'LEFT | CENTER | RIGHT | JUSTIFIED',
      textAlignVertical: 'TOP | CENTER | BOTTOM',
      letterSpacing: 'number',
      lineHeightPx: 'number',
      lineHeightPercent: 'number',
      lineHeightUnit: 'PIXELS | FONT_SIZE | INTRINSIC',
      textCase: 'ORIGINAL | UPPER | LOWER | TITLE | SMALL_CAPS',
      textDecoration: 'NONE | UNDERLINE | STRIKETHROUGH'
    },
    
    Component: {
      key: 'string',
      name: 'string',
      description: 'string',
      componentSetId: 'string',
      documentationLinks: 'string[]'
    },
    
    ComponentSet: {
      key: 'string',
      name: 'string',
      description: 'string',
      documentationLinks: 'string[]'
    },
    
    Style: {
      key: 'string',
      name: 'string',
      description: 'string',
      styleType: 'FILL | TEXT | EFFECT | GRID'
    },
    
    Effect: {
      type: 'DROP_SHADOW | INNER_SHADOW | LAYER_BLUR | BACKGROUND_BLUR',
      visible: 'boolean',
      radius: 'number',
      color: 'Color',
      offset: 'Vector',
      spread: 'number',
      blendMode: 'BlendMode'
    }
  };

  /**
   * Test Authentication
   */
  async testAuth() {
    try {
      const response = await axios.get(`${this.baseURL}/me`, {
        headers: this.headers
      });
      
      console.log('✓ Authentication successful');
      console.log('User:', response.data.handle);
      console.log('Email:', response.data.email);
      return true;
    } catch (error) {
      console.error('✗ Authentication failed:', error.message);
      return false;
    }
  }

  /**
   * Test Rate Limits
   */
  async testRateLimits() {
    console.log('\nTesting rate limits...');
    const results = [];
    
    // Make 10 rapid requests
    for (let i = 0; i < 10; i++) {
      const start = Date.now();
      
      try {
        const response = await axios.get(`${this.baseURL}/me`, {
          headers: this.headers
        });
        
        const elapsed = Date.now() - start;
        
        // Extract rate limit headers
        this.rateLimit.remaining = response.headers['x-ratelimit-remaining'];
        this.rateLimit.reset = response.headers['x-ratelimit-reset'];
        
        results.push({
          request: i + 1,
          elapsed: elapsed + 'ms',
          remaining: this.rateLimit.remaining
        });
      } catch (error) {
        if (error.response?.status === 429) {
          console.log('Rate limit hit at request', i + 1);
          break;
        }
      }
      
      // Small delay between requests
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    
    console.table(results);
    console.log('Rate limit info:', this.rateLimit);
    return results;
  }

  /**
   * Explore File Structure
   */
  async exploreFileStructure(fileKey) {
    console.log('\nExploring file structure...');
    
    try {
      const response = await axios.get(`${this.baseURL}/files/${fileKey}`, {
        headers: this.headers,
        params: {
          depth: 2,
          geometry: 'paths'
        }
      });
      
      const file = response.data;
      
      // Analyze document structure
      const analysis = {
        name: file.name,
        lastModified: file.lastModified,
        version: file.version,
        pages: file.document.children.length,
        components: file.components ? Object.keys(file.components).length : 0,
        styles: file.styles ? Object.keys(file.styles).length : 0,
        nodeTypes: this.countNodeTypes(file.document)
      };
      
      console.log('File Analysis:', analysis);
      
      // Save sample data for reference
      await fs.writeFile(
        '.design/sample-file-structure.json',
        JSON.stringify(file, null, 2)
      );
      
      return analysis;
    } catch (error) {
      console.error('Failed to explore file:', error.message);
      return null;
    }
  }

  /**
   * Count node types in document
   */
  countNodeTypes(node, counts = {}) {
    counts[node.type] = (counts[node.type] || 0) + 1;
    
    if (node.children) {
      for (const child of node.children) {
        this.countNodeTypes(child, counts);
      }
    }
    
    return counts;
  }

  /**
   * Test Style Extraction
   */
  async testStyleExtraction(fileKey) {
    console.log('\nTesting style extraction...');
    
    try {
      const response = await axios.get(`${this.baseURL}/files/${fileKey}`, {
        headers: this.headers
      });
      
      const file = response.data;
      const styles = file.styles || {};
      
      const styleAnalysis = {
        total: Object.keys(styles).length,
        byType: {},
        samples: []
      };
      
      // Analyze styles by type
      for (const [key, style] of Object.entries(styles)) {
        const type = style.styleType;
        styleAnalysis.byType[type] = (styleAnalysis.byType[type] || 0) + 1;
        
        // Save sample of each type
        if (styleAnalysis.samples.length < 5) {
          styleAnalysis.samples.push({
            key,
            name: style.name,
            type: style.styleType,
            description: style.description
          });
        }
      }
      
      console.log('Style Analysis:', styleAnalysis);
      return styleAnalysis;
    } catch (error) {
      console.error('Failed to extract styles:', error.message);
      return null;
    }
  }

  /**
   * Test Component Detection
   */
  async testComponentDetection(fileKey) {
    console.log('\nTesting component detection...');
    
    try {
      const response = await axios.get(`${this.baseURL}/files/${fileKey}`, {
        headers: this.headers
      });
      
      const file = response.data;
      const components = file.components || {};
      const componentSets = file.componentSets || {};
      
      const componentAnalysis = {
        components: Object.keys(components).length,
        componentSets: Object.keys(componentSets).length,
        samples: [],
        variants: {}
      };
      
      // Analyze component structure
      for (const [key, component] of Object.entries(components).slice(0, 5)) {
        componentAnalysis.samples.push({
          key,
          name: component.name,
          description: component.description
        });
        
        // Check if part of component set (variants)
        if (component.componentSetId) {
          const setId = component.componentSetId;
          componentAnalysis.variants[setId] = 
            (componentAnalysis.variants[setId] || 0) + 1;
        }
      }
      
      console.log('Component Analysis:', componentAnalysis);
      return componentAnalysis;
    } catch (error) {
      console.error('Failed to detect components:', error.message);
      return null;
    }
  }

  /**
   * Test Webhook Capabilities
   */
  async testWebhookCapabilities() {
    console.log('\nWebhook Capabilities:');
    console.log('- FILE_UPDATE: File content changes');
    console.log('- FILE_VERSION_UPDATE: New version published');
    console.log('- FILE_DELETE: File deleted');
    console.log('- LIBRARY_PUBLISH: Library published');
    console.log('- FILE_COMMENT: Comment added');
    
    // Note: Actual webhook creation requires team_id
    return {
      eventTypes: [
        'FILE_UPDATE',
        'FILE_VERSION_UPDATE',
        'FILE_DELETE',
        'LIBRARY_PUBLISH',
        'FILE_COMMENT'
      ],
      requirements: {
        endpoint: 'HTTPS URL required',
        authentication: 'Passcode header supported',
        retries: 'Automatic retry on failure',
        maxPayloadSize: '1MB'
      }
    };
  }

  /**
   * Run complete exploration
   */
  async runStudy(fileKey) {
    console.log('='.repeat(50));
    console.log('FIGMA API EXPLORATION STUDY');
    console.log('='.repeat(50));
    
    // 1. Test authentication
    await this.testAuth();
    
    // 2. Test rate limits
    await this.testRateLimits();
    
    // 3. Explore file structure (if fileKey provided)
    if (fileKey) {
      await this.exploreFileStructure(fileKey);
      await this.testStyleExtraction(fileKey);
      await this.testComponentDetection(fileKey);
    } else {
      console.log('\nSkipping file exploration (no fileKey provided)');
    }
    
    // 4. Document webhook capabilities
    const webhooks = await this.testWebhookCapabilities();
    
    // Save findings
    const findings = {
      timestamp: new Date().toISOString(),
      endpoints: this.endpoints,
      dataStructures: Object.keys(this.dataStructures),
      rateLimit: this.rateLimit,
      webhookCapabilities: webhooks
    };
    
    await fs.writeFile(
      '.design/figma-api-findings.json',
      JSON.stringify(findings, null, 2)
    );
    
    console.log('\n✓ Study complete. Findings saved to .design/figma-api-findings.json');
    return findings;
  }
}

// Export for use in other modules
module.exports = FigmaAPIStudy;

// Run if executed directly
if (require.main === module) {
  const study = new FigmaAPIStudy();
  // Pass a Figma file key as command line argument if available
  const fileKey = process.argv[2];
  study.runStudy(fileKey).catch(console.error);
}
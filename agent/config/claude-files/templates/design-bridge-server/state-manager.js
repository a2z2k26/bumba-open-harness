/**
 * State Manager
 * Manages component states and transitions for design systems
 * Sprint 3: State Management System
 */

const EventEmitter = require('events');

class StateManager extends EventEmitter {
  constructor() {
    super();
    this.name = 'StateManager';
    this.version = '1.0.0';

    // State definitions
    this.states = {
      // Interactive states
      default: { name: 'default', priority: 0, persistent: true },
      hover: { name: 'hover', priority: 1, persistent: false },
      focus: { name: 'focus', priority: 2, persistent: false },
      active: { name: 'active', priority: 3, persistent: false },
      disabled: { name: 'disabled', priority: 10, persistent: true },

      // Validation states
      valid: { name: 'valid', priority: 4, persistent: true },
      invalid: { name: 'invalid', priority: 5, persistent: true },
      warning: { name: 'warning', priority: 4, persistent: true },

      // Loading states
      loading: { name: 'loading', priority: 8, persistent: true },
      success: { name: 'success', priority: 6, persistent: false },
      error: { name: 'error', priority: 7, persistent: true },

      // Selection states
      selected: { name: 'selected', priority: 3, persistent: true },
      indeterminate: { name: 'indeterminate', priority: 3, persistent: true }
    };

    // State transitions
    this.transitions = new Map();
    this.initializeTransitions();

    // State inheritance patterns
    this.inheritance = new Map();
    this.initializeInheritance();

    // Component state registry
    this.componentStates = new Map();

    // State combination rules
    this.combinationRules = this.initializeCombinationRules();
  }

  /**
   * Initialize state transitions
   */
  initializeTransitions() {
    // Define valid state transitions
    this.transitions.set('default', ['hover', 'focus', 'active', 'disabled', 'loading', 'selected']);
    this.transitions.set('hover', ['default', 'active', 'focus', 'disabled']);
    this.transitions.set('focus', ['default', 'hover', 'active', 'disabled']);
    this.transitions.set('active', ['default', 'hover', 'focus', 'disabled']);
    this.transitions.set('disabled', ['default']);
    this.transitions.set('loading', ['default', 'success', 'error']);
    this.transitions.set('success', ['default']);
    this.transitions.set('error', ['default', 'loading']);
    this.transitions.set('selected', ['default', 'hover', 'focus', 'disabled']);
  }

  /**
   * Initialize state inheritance patterns
   */
  initializeInheritance() {
    // Define which properties are inherited from parent states
    this.inheritance.set('hover', {
      inherits: ['default'],
      overrides: ['background', 'borderColor', 'boxShadow', 'transform']
    });

    this.inheritance.set('focus', {
      inherits: ['default'],
      overrides: ['outline', 'borderColor', 'boxShadow']
    });

    this.inheritance.set('active', {
      inherits: ['default'],
      overrides: ['background', 'transform', 'boxShadow']
    });

    this.inheritance.set('disabled', {
      inherits: ['default'],
      overrides: ['opacity', 'cursor', 'pointerEvents']
    });

    this.inheritance.set('selected', {
      inherits: ['default'],
      overrides: ['background', 'borderColor', 'color']
    });
  }

  /**
   * Initialize combination rules
   */
  initializeCombinationRules() {
    return {
      // Mutually exclusive states
      exclusive: [
        ['default', 'disabled'],
        ['loading', 'success', 'error'],
        ['valid', 'invalid', 'warning']
      ],

      // States that can combine
      combinable: [
        ['hover', 'selected'],
        ['focus', 'selected'],
        ['focus', 'invalid'],
        ['hover', 'valid']
      ],

      // Priority overrides
      overrides: {
        disabled: ['hover', 'focus', 'active'],
        loading: ['hover', 'focus', 'active'],
        error: ['hover', 'focus']
      }
    };
  }

  /**
   * Register component with state management
   */
  registerComponent(componentId, config = {}) {
    const componentState = {
      id: componentId,
      currentState: 'default',
      availableStates: config.states || Object.keys(this.states),
      stateHistory: [],
      properties: new Map(),
      listeners: new Map(),
      config
    };

    this.componentStates.set(componentId, componentState);
    this.emit('component:registered', { componentId, state: componentState });

    return componentState;
  }

  /**
   * Transition component to new state
   */
  async transitionTo(componentId, newState, options = {}) {
    const component = this.componentStates.get(componentId);

    if (!component) {
      throw new Error(`Component ${componentId} not registered`);
    }

    const currentState = component.currentState;

    // Validate transition
    if (!this.isValidTransition(currentState, newState)) {
      throw new Error(`Invalid transition from ${currentState} to ${newState}`);
    }

    // Apply transition
    const transition = {
      from: currentState,
      to: newState,
      timestamp: Date.now(),
      duration: options.duration || 200,
      easing: options.easing || 'ease-in-out',
      properties: await this.calculateTransitionProperties(component, newState)
    };

    // Update component state
    component.currentState = newState;
    component.stateHistory.push(transition);

    // Emit transition event
    this.emit('state:transition', {
      componentId,
      transition,
      component
    });

    return transition;
  }

  /**
   * Calculate properties for state transition
   */
  async calculateTransitionProperties(component, targetState) {
    const properties = {};
    const stateConfig = this.states[targetState];
    const inheritance = this.inheritance.get(targetState);

    // Get base properties
    if (inheritance?.inherits) {
      for (const parentState of inheritance.inherits) {
        const parentProps = component.properties.get(parentState) || {};
        Object.assign(properties, parentProps);
      }
    }

    // Apply state-specific properties
    const stateProps = component.properties.get(targetState) || {};
    Object.assign(properties, stateProps);

    // Apply overrides
    if (inheritance?.overrides) {
      for (const prop of inheritance.overrides) {
        if (stateProps[prop] !== undefined) {
          properties[prop] = stateProps[prop];
        }
      }
    }

    return properties;
  }

  /**
   * Define properties for a state
   */
  defineStateProperties(componentId, state, properties) {
    const component = this.componentStates.get(componentId);

    if (!component) {
      throw new Error(`Component ${componentId} not registered`);
    }

    component.properties.set(state, properties);

    this.emit('properties:defined', {
      componentId,
      state,
      properties
    });

    return properties;
  }

  /**
   * Check if transition is valid
   */
  isValidTransition(from, to) {
    const allowedTransitions = this.transitions.get(from);
    return allowedTransitions && allowedTransitions.includes(to);
  }

  /**
   * Check if states can be combined
   */
  canCombineStates(state1, state2) {
    // Check exclusive rules
    for (const exclusive of this.combinationRules.exclusive) {
      if (exclusive.includes(state1) && exclusive.includes(state2)) {
        return false;
      }
    }

    // Check combinable rules
    for (const combinable of this.combinationRules.combinable) {
      if (combinable.includes(state1) && combinable.includes(state2)) {
        return true;
      }
    }

    // Default to false for safety
    return false;
  }

  /**
   * Get combined state properties
   */
  getCombinedStateProperties(states) {
    const combined = {};
    const sortedStates = states.sort((a, b) => {
      const priorityA = this.states[a]?.priority || 0;
      const priorityB = this.states[b]?.priority || 0;
      return priorityA - priorityB;
    });

    for (const state of sortedStates) {
      const stateConfig = this.states[state];
      if (!stateConfig) continue;

      // Check for overrides
      const overrides = this.combinationRules.overrides[state];
      if (overrides) {
        // This state overrides others
        for (const overridden of overrides) {
          if (sortedStates.includes(overridden)) {
            // Remove overridden state properties
            const index = sortedStates.indexOf(overridden);
            if (index > -1) {
              sortedStates.splice(index, 1);
            }
          }
        }
      }
    }

    // Apply remaining states in priority order
    for (const state of sortedStates) {
      Object.assign(combined, this.states[state]);
    }

    return combined;
  }

  /**
   * Add state listener for component
   */
  addStateListener(componentId, state, callback) {
    const component = this.componentStates.get(componentId);

    if (!component) {
      throw new Error(`Component ${componentId} not registered`);
    }

    if (!component.listeners.has(state)) {
      component.listeners.set(state, new Set());
    }

    component.listeners.get(state).add(callback);

    return () => {
      component.listeners.get(state)?.delete(callback);
    };
  }

  /**
   * Generate state machine for component
   */
  generateStateMachine(componentId) {
    const component = this.componentStates.get(componentId);

    if (!component) {
      throw new Error(`Component ${componentId} not registered`);
    }

    return {
      id: componentId,
      initial: 'default',
      states: this.generateStateNodes(component),
      transitions: this.generateTransitionNodes(component),
      guards: this.generateGuards(component),
      actions: this.generateActions(component)
    };
  }

  /**
   * Generate state nodes for state machine
   */
  generateStateNodes(component) {
    const nodes = {};

    for (const state of component.availableStates) {
      nodes[state] = {
        name: state,
        properties: component.properties.get(state) || {},
        entry: `enter_${state}`,
        exit: `exit_${state}`,
        activities: []
      };
    }

    return nodes;
  }

  /**
   * Generate transition nodes
   */
  generateTransitionNodes(component) {
    const transitions = [];

    for (const [from, targets] of this.transitions.entries()) {
      if (!component.availableStates.includes(from)) continue;

      for (const to of targets) {
        if (!component.availableStates.includes(to)) continue;

        transitions.push({
          from,
          to,
          event: `TRANSITION_TO_${to.toUpperCase()}`,
          guard: `canTransitionTo_${to}`,
          action: `transition_${from}_to_${to}`
        });
      }
    }

    return transitions;
  }

  /**
   * Get current state of component
   */
  getCurrentState(componentId) {
    const component = this.componentStates.get(componentId);
    return component?.currentState;
  }

  /**
   * Get state history for component
   */
  getStateHistory(componentId) {
    const component = this.componentStates.get(componentId);
    return component?.stateHistory || [];
  }

  /**
   * Reset component to default state
   */
  resetToDefault(componentId) {
    return this.transitionTo(componentId, 'default');
  }

  /**
   * Export state configuration
   */
  exportStateConfiguration() {
    return {
      states: this.states,
      transitions: Array.from(this.transitions.entries()),
      inheritance: Array.from(this.inheritance.entries()),
      combinationRules: this.combinationRules
    };
  }
}

module.exports = StateManager;
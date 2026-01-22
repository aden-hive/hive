/**
 * Control Socket Initialization
 *
 * Wrapper for initializing control plane WebSockets with proper dependencies.
 */

import { Server } from 'socket.io';
import { createAdapter } from '@socket.io/redis-adapter';
import { Emitter } from '@socket.io/redis-emitter';
import Redis from 'ioredis';
import { getErrorMessage } from '../utils/error';
import type { Server as HttpServer } from 'http';

import initAdenControlSockets, { setUserDbService } from '../services/control/control_sockets';

interface ControlEmitter {
  emitPolicyUpdate: (teamId: string | number, policyId: string | null, policy: unknown) => void;
  emitCommand: (teamId: string | number, command: { action: string; [key: string]: unknown }) => void;
  emitAlert: (teamId: string | number, policyId: string | null, alert: unknown) => void;
  emitToInstance: (teamId: string | number, instanceId: string, message: unknown) => boolean;
  getConnectedCount: (teamId: string | number) => number;
  getConnectedInstances: (teamId: string | number) => Array<{
    instance_id: string;
    policy_id: string | null;
    connected_at: string;
    last_heartbeat: string;
  }>;
  getTotalConnectedCount: () => number;
}

interface MockEmitter {
  of: () => {
    to: () => { emit: () => void };
    emit: () => void;
  };
}

/**
 * Initialize WebSockets for the control plane
 * @param server - HTTP server instance
 * @returns Promise<{io: Server, controlEmitter: Object}>
 */
async function initializeSockets(server: HttpServer): Promise<{ io: Server; controlEmitter: ControlEmitter }> {
  // Create Socket.IO server
  const io = new Server(server, {
    cors: {
      origin: '*',
      methods: ['GET', 'POST'],
    },
    transports: ['websocket', 'polling'],
  });

  let controlEmitter: ControlEmitter;

  // Try to setup Redis adapter for scaling
  if (process.env.REDIS_URL) {
    try {
      const pubClient = new Redis(process.env.REDIS_URL);
      const subClient = pubClient.duplicate();

      await Promise.all([
        new Promise<void>((resolve) => pubClient.on('connect', resolve)),
        new Promise<void>((resolve) => subClient.on('connect', resolve)),
      ]);

      io.adapter(createAdapter(pubClient, subClient));

      // Create Redis emitter for cross-instance communication
      const redisEmitter = new Emitter(pubClient);
      controlEmitter = initAdenControlSockets(io, redisEmitter as unknown as { of: (namespace: string) => { to: (room: string) => { emit: (event: string, payload: unknown) => void }; emit: (event: string, payload: unknown) => void } });

      console.log('[Sockets] Redis adapter connected');
    } catch (err: unknown) {
      console.warn('[Sockets] Redis connection failed, using local adapter:', getErrorMessage(err));
      // Create a mock emitter for local development
      const mockEmitter: MockEmitter = {
        of: () => ({
          to: () => ({ emit: () => {} }),
          emit: () => {},
        }),
      };
      controlEmitter = initAdenControlSockets(io, mockEmitter as unknown as { of: (namespace: string) => { to: (room: string) => { emit: (event: string, payload: unknown) => void }; emit: (event: string, payload: unknown) => void } });
    }
  } else {
    console.warn('[Sockets] No REDIS_URL configured, using local adapter');
    // Create a mock emitter for local development
    const mockEmitter: MockEmitter = {
      of: () => ({
        to: () => ({ emit: () => {} }),
        emit: () => {},
      }),
    };
    controlEmitter = initAdenControlSockets(io, mockEmitter as unknown as { of: (namespace: string) => { to: (room: string) => { emit: (event: string, payload: unknown) => void }; emit: (event: string, payload: unknown) => void } });
  }

  return { io, controlEmitter };
}

export { initializeSockets, setUserDbService };

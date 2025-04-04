import socket
import threading
import json
import time
from datetime import datetime

class ChatServer:
    def __init__(self, host='0.0.0.0', port=9090):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = {}  # {client_socket: {"nickname": nickname, "channel": channel}}
        self.channels = {"general": set()}  # Default channel
        self.lock = threading.Lock()
        self.running = True
        
    def start_server(self):
        """Start the server and begin listening for connections."""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(100)  # Queue up to 100 connections
            print(f"[SERVER] Started on {self.host}:{self.port}")
            
            # Start a thread to monitor server health
            health_thread = threading.Thread(target=self.monitor_health)
            health_thread.daemon = True
            health_thread.start()
            
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    print(f"[SERVER] New connection from {client_address}")
                    
                    # Start a new thread to handle this client
                    client_thread = threading.Thread(target=self.handle_client, args=(client_socket, client_address))
                    client_thread.daemon = True
                    client_thread.start()
                    
                except Exception as e:
                    if self.running:
                        print(f"[SERVER] Error accepting connection: {e}")
                    else:
                        break
        except Exception as e:
            print(f"[SERVER] Failed to start server: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Gracefully shut down the server."""
        self.running = False
        print("[SERVER] Shutting down...")
        
        # Notify all clients of shutdown
        shutdown_msg = self.create_message("SERVER", "all", "server_shutdown", "Server is shutting down.")
        self.broadcast(shutdown_msg)
        
        # Close all client connections
        with self.lock:
            for client_socket in list(self.clients.keys()):
                try:
                    client_socket.close()
                except:
                    pass
            self.clients.clear()
        
        # Close server socket
        try:
            self.server_socket.close()
        except:
            pass
        print("[SERVER] Shutdown complete")
    
    def monitor_health(self):
        """Monitor server health and log statistics periodically."""
        while self.running:
            with self.lock:
                client_count = len(self.clients)
                channel_stats = {channel: len(members) for channel, members in self.channels.items()}
            
            print(f"[HEALTH] Active clients: {client_count}")
            print(f"[HEALTH] Channel statistics: {channel_stats}")
            
            time.sleep(60)  # Check every minute
    
    def handle_client(self, client_socket, address):
        """Handle communication with a client."""
        try:
            # First message should be the registration with nickname
            registration = self.receive_message(client_socket)
            if not registration or registration['type'] != 'register':
                client_socket.close()
                return
            
            nickname = registration['content']
            
            # Check if nickname is already in use
            with self.lock:
                if any(client_info['nickname'] == nickname for client_info in self.clients.values()):
                    self.send_message(client_socket, self.create_message(
                        "SERVER", nickname, "error", "Nickname already in use. Please choose another one."
                    ))
                    client_socket.close()
                    return
                
                # Register the client
                self.clients[client_socket] = {"nickname": nickname, "channel": "general"}
                self.channels["general"].add(client_socket)
            
            # Notify the client of successful registration
            welcome_msg = self.create_message("SERVER", nickname, "info", f"Welcome {nickname}! You are in the 'general' channel.")
            self.send_message(client_socket, welcome_msg)
            
            # Notify other clients
            join_msg = self.create_message("SERVER", "all", "info", f"{nickname} has joined the chat.")
            self.broadcast(join_msg, exclude=client_socket)
            
            # Send list of available channels
            channels_list = list(self.channels.keys())
            channels_msg = self.create_message("SERVER", nickname, "channels_list", channels_list)
            self.send_message(client_socket, channels_msg)
            
            # Main loop to receive messages from this client
            while self.running:
                message = self.receive_message(client_socket)
                if not message:
                    break
                
                self.process_message(client_socket, message)
                
        except Exception as e:
            print(f"[SERVER] Error handling client {address}: {e}")
        finally:
            self.remove_client(client_socket)
    
    def process_message(self, client_socket, message):
        """Process a message from a client."""
        sender = self.clients[client_socket]['nickname']
        
        if message['type'] == 'chat':
            # Regular chat message to current channel
            current_channel = self.clients[client_socket]['channel']
            forwarded_msg = self.create_message(sender, current_channel, 'chat', message['content'])
            self.broadcast_to_channel(current_channel, forwarded_msg, exclude=None if message.get('echo', False) else client_socket)
        
        elif message['type'] == 'private':
            # Private message to a specific user
            recipient = message['recipient']
            recipient_socket = None
            
            with self.lock:
                for sock, info in self.clients.items():
                    if info['nickname'] == recipient:
                        recipient_socket = sock
                        break
            
            if recipient_socket:
                forwarded_msg = self.create_message(sender, recipient, 'private', message['content'])
                self.send_message(recipient_socket, forwarded_msg)
                
                # Echo back to sender if they want to see their sent messages
                if message.get('echo', False):
                    self.send_message(client_socket, forwarded_msg)
            else:
                error_msg = self.create_message("SERVER", sender, "error", f"User '{recipient}' not found.")
                self.send_message(client_socket, error_msg)
        
        elif message['type'] == 'join_channel':
            # Join a channel
            channel_name = message['content']
            
            with self.lock:
                # Create channel if it doesn't exist
                if channel_name not in self.channels:
                    self.channels[channel_name] = set()
                
                # Remove from current channel
                current_channel = self.clients[client_socket]['channel']
                if current_channel:
                    self.channels[current_channel].discard(client_socket)
                
                # Add to new channel
                self.channels[channel_name].add(client_socket)
                self.clients[client_socket]['channel'] = channel_name
            
            # Notify the client
            channel_msg = self.create_message("SERVER", sender, "info", f"You joined channel '{channel_name}'")
            self.send_message(client_socket, channel_msg)
            
            # Notify other users in the channel
            join_msg = self.create_message("SERVER", channel_name, "info", f"{sender} has joined this channel.")
            self.broadcast_to_channel(channel_name, join_msg, exclude=client_socket)
        
        elif message['type'] == 'create_channel':
            # Create a new channel
            channel_name = message['content']
            
            with self.lock:
                if channel_name in self.channels:
                    error_msg = self.create_message("SERVER", sender, "error", f"Channel '{channel_name}' already exists.")
                    self.send_message(client_socket, error_msg)
                else:
                    self.channels[channel_name] = set()
                    success_msg = self.create_message("SERVER", sender, "info", f"Channel '{channel_name}' created.")
                    self.send_message(client_socket, success_msg)
                    
                    # Update all clients with new channel list
                    channels_list = list(self.channels.keys())
                    channels_msg = self.create_message("SERVER", "all", "channels_list", channels_list)
                    self.broadcast(channels_msg)
        
        elif message['type'] == 'list_users':
            # List users in the specified channel or current channel
            channel_name = message.get('content', self.clients[client_socket]['channel'])
            
            with self.lock:
                if channel_name in self.channels:
                    users = [self.clients[sock]['nickname'] for sock in self.channels[channel_name]]
                    users_msg = self.create_message("SERVER", sender, "users_list", users)
                    self.send_message(client_socket, users_msg)
                else:
                    error_msg = self.create_message("SERVER", sender, "error", f"Channel '{channel_name}' does not exist.")
                    self.send_message(client_socket, error_msg)
    
    def remove_client(self, client_socket):
        """Remove a client from the server."""
        with self.lock:
            if client_socket in self.clients:
                nickname = self.clients[client_socket]['nickname']
                channel = self.clients[client_socket]['channel']
                
                # Remove from channel
                if channel in self.channels:
                    self.channels[channel].discard(client_socket)
                
                # Remove from clients dictionary
                del self.clients[client_socket]
                
                # Notify other clients
                leave_msg = self.create_message("SERVER", "all", "info", f"{nickname} has left the chat.")
                self.broadcast(leave_msg)
        
        try:
            client_socket.close()
        except:
            pass
    
    def broadcast(self, message, exclude=None):
        """Broadcast a message to all connected clients."""
        with self.lock:
            for client_socket in list(self.clients.keys()):
                if client_socket != exclude:
                    try:
                        self.send_message(client_socket, message)
                    except:
                        pass  # Client might be disconnected
    
    def broadcast_to_channel(self, channel, message, exclude=None):
        """Broadcast a message to all clients in a specific channel."""
        if channel not in self.channels:
            return
        
        with self.lock:
            for client_socket in list(self.channels[channel]):
                if client_socket != exclude:
                    try:
                        self.send_message(client_socket, message)
                    except:
                        pass  # Client might be disconnected
    
    @staticmethod
    def create_message(sender, recipient, msg_type, content):
        """Create a formatted message."""
        return {
            'sender': sender,
            'recipient': recipient,
            'type': msg_type,
            'content': content,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }
    
    @staticmethod
    def send_message(client_socket, message):
        """Send a message to a client."""
        try:
            message_json = json.dumps(message)
            message_bytes = (message_json + '\n').encode('utf-8')
            client_socket.sendall(message_bytes)
        except Exception as e:
            raise Exception(f"Failed to send message: {e}")
    
    @staticmethod
    def receive_message(client_socket):
        """Receive a message from a client."""
        try:
            buffer = ""
            while True:
                data = client_socket.recv(4096).decode('utf-8')
                if not data:
                    return None  # Client disconnected
                
                buffer += data
                if '\n' in buffer:
                    message_json, buffer = buffer.split('\n', 1)
                    return json.loads(message_json)
        except Exception:
            return None  # Error receiving message


if __name__ == "__main__":
    try:
        server = ChatServer()
        print("Starting chat server. Press Ctrl+C to stop.")
        server.start_server()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    except Exception as e:
        print(f"Unexpected error: {e}")
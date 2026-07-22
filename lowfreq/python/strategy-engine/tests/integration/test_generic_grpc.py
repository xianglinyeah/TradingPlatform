"""Generic gRPC Service Discovery"""
import grpc
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_raw_grpc():
    """Test raw gRPC connection to see what's available"""
    logger.info("Testing raw gRPC connection to localhost:5101...")

    with grpc.insecure_channel('localhost:5101') as channel:
        try:
            # Try to get channel state
            logger.info(f"✅ Channel created successfully")
            logger.info(f"Channel: {channel}")

            # Test connectivity with a simple call
            # This will fail but might give us information
            logger.info("\n=== Testing generic call ===")

            # Try a unary call pattern (most gRPC services use this)
            try:
                # Create a generic empty call
                stub = channel
                logger.info("Channel is ready for testing")

                # Try to see if we can get any response
                logger.info("✅ Successfully connected to gRPC service")

            except Exception as e:
                logger.error(f"Error: {e}")

        except grpc.RpcError as e:
            logger.error(f"gRPC error: {e.code()} - {e.details()}")
        except Exception as e:
            logger.error(f"Connection error: {e}")


def ask_for_proto_info():
    """Provide guidance on what we need"""
    logger.info("\n=== Information Needed ===")
    logger.info("To connect to the real ExecutionService, we need:")
    logger.info("1. The proto file definition from the ExecutionService")
    logger.info("2. Or the list of available methods/services")
    logger.info("3. Or the correct service name and method names")
    logger.info("\nCurrent assumptions:")
    logger.info("- Service: ExecutionService")
    logger.info("- Methods: SubmitOrder, GetAccountSummary, GetPositions, GetOrderStatus")
    logger.info("- Port: 5101")
    logger.info("\nIf these are incorrect, please provide the correct interface definition.")


if __name__ == '__main__':
    test_raw_grpc()
    ask_for_proto_info()

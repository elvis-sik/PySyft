# stdlib
import os
from secrets import token_hex
import time

# third party
from faker import Faker
import pytest

# syft absolute
import syft as sy
from syft.abstract_node import NodeType
from syft.client.datasite_client import DatasiteClient
from syft.client.enclave_client import EnclaveClient
from syft.client.gateway_client import GatewayClient
from syft.service.network.network_service import NodePeerAssociationStatus
from syft.service.network.node_peer import NodePeer
from syft.service.network.node_peer import NodePeerConnectionStatus
from syft.service.network.utils import PeerHealthCheckTask
from syft.service.request.request import Request
from syft.service.response import SyftSuccess
from syft.service.user.user_roles import ServiceRole


def _launch(
    node_type: NodeType,
    association_request_auto_approval: bool = True,
    port: int | str | None = None,
):
    return sy.orchestra.launch(
        name=token_hex(8),
        node_type=node_type,
        dev_mode=True,
        reset=True,
        local_db=True,
        association_request_auto_approval=association_request_auto_approval,
        port=port,
        background_tasks=True,
    )


@pytest.fixture
def gateway():
    node = _launch(NodeType.GATEWAY)
    yield node
    node.python_node.cleanup()
    node.land()


@pytest.fixture(params=[True, False])
def gateway_association_request_auto_approval(request: pytest.FixtureRequest):
    node = _launch(NodeType.GATEWAY, association_request_auto_approval=request.param)
    yield (request.param, node)
    node.python_node.cleanup()
    node.land()


@pytest.fixture
def datasite():
    node = _launch(NodeType.DATASITE)
    yield node
    node.python_node.cleanup()
    node.land()


@pytest.fixture
def datasite_2():
    node = _launch(NodeType.DATASITE)
    yield node
    node.python_node.cleanup()
    node.land()


@pytest.fixture
def enclave():
    node = _launch(NodeType.ENCLAVE)
    yield node
    node.python_node.cleanup()
    node.land()


@pytest.fixture
def gateway_webserver():
    node = _launch(node_type=NodeType.GATEWAY, port="auto")
    yield node
    node.land()


@pytest.fixture
def datasite_webserver():
    node = _launch(NodeType.DATASITE, port="auto")
    yield node
    node.land()


@pytest.fixture
def datasite_2_webserver():
    node = _launch(NodeType.DATASITE, port="auto")
    yield node
    node.land()


@pytest.fixture(scope="function")
def set_network_json_env_var(gateway_webserver):
    """Set the environment variable for the network registry JSON string."""
    json_string = f"""
        {{
            "2.0.0": {{
                "gateways": [
                    {{
                        "name": "{gateway_webserver.name}",
                        "host_or_ip": "localhost",
                        "protocol": "http",
                        "port": "{gateway_webserver.port}",
                        "admin_email": "support@openmined.org",
                        "website": "https://www.openmined.org/",
                        "slack": "https://slack.openmined.org/",
                        "slack_channel": "#support"
                    }}
                ]
            }}
        }}
    """
    os.environ["NETWORK_REGISTRY_JSON"] = json_string
    yield
    # Clean up the environment variable after all tests in the module have run
    del os.environ["NETWORK_REGISTRY_JSON"]


@pytest.mark.local_node
def test_create_gateway(
    set_network_json_env_var,
    gateway_webserver,
    datasite_webserver,
    datasite_2_webserver,
):
    assert isinstance(sy.gateways, sy.NetworkRegistry)
    assert len(sy.gateways) == 1
    assert len(sy.gateways.all_networks) == 1
    assert sy.gateways.all_networks[0]["name"] == gateway_webserver.name
    assert len(sy.gateways.online_networks) == 1
    assert sy.gateways.online_networks[0]["name"] == gateway_webserver.name

    gateway_client: GatewayClient = gateway_webserver.login(
        email="info@openmined.org",
        password="changethis",
    )
    res = gateway_client.settings.allow_association_request_auto_approval(enable=True)
    assert isinstance(res, SyftSuccess)

    datasite_client: DatasiteClient = datasite_webserver.login(
        email="info@openmined.org",
        password="changethis",
    )
    datasite_client_2: DatasiteClient = datasite_2_webserver.login(
        email="info@openmined.org",
        password="changethis",
    )
    result = datasite_client.connect_to_gateway(handle=gateway_webserver)
    assert isinstance(result, SyftSuccess)
    result = datasite_client_2.connect_to_gateway(handle=gateway_webserver)
    assert isinstance(result, SyftSuccess)

    time.sleep(PeerHealthCheckTask.repeat_time * 2 + 1)
    assert len(sy.datasites.all_datasites) == 2
    assert len(sy.datasites.online_datasites) == 2
    # check for peer connection status
    for peer in gateway_client.api.services.network.get_all_peers():
        assert peer.ping_status == NodePeerConnectionStatus.ACTIVE

    # check the guest client
    client = gateway_webserver.client
    assert isinstance(client, GatewayClient)
    assert client.metadata.node_type == NodeType.GATEWAY.value


@pytest.mark.local_node
def test_datasite_connect_to_gateway(
    gateway_association_request_auto_approval, datasite
):
    association_request_auto_approval, gateway = (
        gateway_association_request_auto_approval
    )
    gateway_client: GatewayClient = gateway.login(
        email="info@openmined.org",
        password="changethis",
    )
    datasite_client: DatasiteClient = datasite.login(
        email="info@openmined.org",
        password="changethis",
    )

    result = datasite_client.connect_to_gateway(handle=gateway)

    if association_request_auto_approval:
        assert isinstance(result, SyftSuccess)
    else:
        assert isinstance(result, Request)
        r = gateway_client.api.services.request.get_all()[-1].approve()
        assert isinstance(r, SyftSuccess)

    # check priority
    all_peers = gateway_client.api.services.network.get_all_peers()
    assert all_peers[0].node_routes[0].priority == 1

    # Try again (via client approach)
    result_2 = datasite_client.connect_to_gateway(via_client=gateway_client)
    assert isinstance(result_2, SyftSuccess)

    assert len(datasite_client.peers) == 1
    assert len(gateway_client.peers) == 1

    proxy_datasite_client = gateway_client.peers[0]
    datasite_peer = datasite_client.peers[0]

    assert isinstance(proxy_datasite_client, DatasiteClient)
    assert isinstance(datasite_peer, NodePeer)

    # Datasite's peer is a gateway and vice-versa
    assert datasite_peer.node_type == NodeType.GATEWAY

    assert gateway_client.name == datasite_peer.name
    assert datasite_client.name == proxy_datasite_client.name

    assert len(gateway_client.datasites) == 1
    assert len(gateway_client.enclaves) == 0

    assert proxy_datasite_client.metadata == datasite_client.metadata
    assert proxy_datasite_client.user_role == ServiceRole.NONE

    datasite_client = datasite_client.login(
        email="info@openmined.org", password="changethis"
    )
    proxy_datasite_client = proxy_datasite_client.login(
        email="info@openmined.org", password="changethis"
    )

    assert proxy_datasite_client.logged_in_user == "info@openmined.org"
    assert proxy_datasite_client.user_role == ServiceRole.ADMIN
    assert proxy_datasite_client.credentials == datasite_client.credentials
    assert (
        proxy_datasite_client.api.endpoints.keys()
        == datasite_client.api.endpoints.keys()
    )

    # check priority
    all_peers = gateway_client.api.services.network.get_all_peers()
    assert all_peers[0].node_routes[0].priority == 1


@pytest.mark.local_node
def test_datasite_connect_to_gateway_routes_priority(
    gateway, datasite, datasite_2
) -> None:
    """
    A test for routes' priority (PythonNodeRoute)
    """
    gateway_client: GatewayClient = gateway.login(
        email="info@openmined.org",
        password="changethis",
    )
    datasite_client: DatasiteClient = datasite.login(
        email="info@openmined.org",
        password="changethis",
    )

    result = datasite_client.connect_to_gateway(handle=gateway)
    assert isinstance(result, SyftSuccess)

    all_peers = gateway_client.api.services.network.get_all_peers()
    assert len(all_peers) == 1
    datasite_1_routes = all_peers[0].node_routes
    assert datasite_1_routes[0].priority == 1

    # reconnect to the gateway
    result = datasite_client.connect_to_gateway(via_client=gateway_client)
    assert isinstance(result, SyftSuccess)
    all_peers = gateway_client.api.services.network.get_all_peers()
    assert len(all_peers) == 1
    datasite_1_routes = all_peers[0].node_routes
    assert datasite_1_routes[0].priority == 1

    # another datasite client connects to the gateway
    datasite_client_2: DatasiteClient = datasite_2.login(
        email="info@openmined.org",
        password="changethis",
    )
    result = datasite_client_2.connect_to_gateway(handle=gateway)
    assert isinstance(result, SyftSuccess)

    all_peers = gateway_client.api.services.network.get_all_peers()
    assert len(all_peers) == 2
    for peer in all_peers:
        assert peer.node_routes[0].priority == 1


@pytest.mark.local_node
def test_enclave_connect_to_gateway(faker: Faker, gateway, enclave):
    gateway_client = gateway.client
    enclave_client: EnclaveClient = enclave.client

    result = enclave_client.connect_to_gateway(handle=gateway)
    assert isinstance(result, SyftSuccess)

    # Try via client approach
    result_2 = enclave_client.connect_to_gateway(via_client=gateway_client)
    assert isinstance(result_2, SyftSuccess)

    assert len(enclave_client.peers) == 1
    assert len(gateway_client.peers) == 1

    proxy_enclave_client = gateway_client.peers[0]
    enclave_peer = enclave_client.peers[0]

    assert isinstance(proxy_enclave_client, EnclaveClient)
    assert isinstance(enclave_peer, NodePeer)

    assert gateway_client.name == enclave_peer.name
    assert enclave_client.name == proxy_enclave_client.name

    # Datasite's peer is a gateway and vice-versa
    assert enclave_peer.node_type == NodeType.GATEWAY

    assert len(gateway_client.datasites) == 0
    assert len(gateway_client.enclaves) == 1

    assert proxy_enclave_client.metadata == enclave_client.metadata
    assert proxy_enclave_client.user_role == ServiceRole.NONE

    # add a new user to enclave
    user_email, password = faker.email(), "password"
    enclave_client.register(
        name=faker.name(),
        email=user_email,
        password=password,
        password_verify=password,
    )

    enclave_client = enclave_client.login(email=user_email, password=password)
    proxy_enclave_client = proxy_enclave_client.login(
        email=user_email, password=password
    )

    assert proxy_enclave_client.logged_in_user == user_email
    assert proxy_enclave_client.user_role == enclave_client.user_role
    assert proxy_enclave_client.credentials == enclave_client.credentials
    assert (
        proxy_enclave_client.api.endpoints.keys() == enclave_client.api.endpoints.keys()
    )


@pytest.mark.local_node
@pytest.mark.parametrize(
    "gateway_association_request_auto_approval", [False], indirect=True
)
def test_repeated_association_requests_peers_health_check(
    gateway_association_request_auto_approval, datasite
):
    _, gateway = gateway_association_request_auto_approval
    gateway_client: GatewayClient = gateway.login(
        email="info@openmined.org",
        password="changethis",
    )
    datasite_client: DatasiteClient = datasite.login(
        email="info@openmined.org",
        password="changethis",
    )

    result = datasite_client.connect_to_gateway(handle=gateway)
    assert isinstance(result, Request)

    result = datasite_client.connect_to_gateway(handle=gateway)
    assert isinstance(result, Request)

    r = gateway_client.api.services.request.get_all()[-1].approve()
    assert isinstance(r, SyftSuccess)

    result = datasite_client.connect_to_gateway(handle=gateway)
    assert isinstance(result, SyftSuccess)

    # the gateway client checks that the peer is associated
    res = gateway_client.api.services.network.check_peer_association(
        peer_id=datasite_client.id
    )
    assert isinstance(res, NodePeerAssociationStatus)
    assert res.value == "PEER_ASSOCIATED"
